import os
import time
import socket
import fcntl
import struct
import threading

from flask import Flask, jsonify, render_template_string


app = Flask(__name__)

INTERFACE = "eth0"

RX_PATH = f"/sys/class/net/{INTERFACE}/statistics/rx_bytes"
TX_PATH = f"/sys/class/net/{INTERFACE}/statistics/tx_bytes"

SAMPLE_INTERVAL = 1.0
HISTORY_SIZE = 600


def get_interface_ip(interface):
    try:
        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        address = fcntl.ioctl(
            sock.fileno(),
            0x8915,
            struct.pack(
                "256s",
                interface.encode()[:15]
            )
        )[20:24]

        sock.close()

        return socket.inet_ntoa(address)

    except Exception:
        return "0.0.0.0"


def get_interfaces():
    try:
        return sorted(
            name
            for name in os.listdir("/sys/class/net")
            if os.path.isdir(
                f"/sys/class/net/{name}"
            )
        )
    except Exception:
        return [INTERFACE]


class NetworkMonitor:

    def __init__(self):
        self.lock = threading.Lock()

        self.rx_bytes = 0
        self.tx_bytes = 0

        self.rx_rate = 0.0
        self.tx_rate = 0.0

        self.rx_history = []
        self.tx_history = []

        self.rx_min = None
        self.tx_min = None

        self.rx_max = 0.0
        self.tx_max = 0.0

        self.thread = threading.Thread(
            target=self.run,
            daemon=True
        )

        self.thread.start()

    def read_counter(self, path):
        try:
            with open(path, "r") as file:
                return int(
                    file.read().strip()
                )
        except Exception:
            return 0

    def run(self):
        previous_rx = self.read_counter(
            RX_PATH
        )

        previous_tx = self.read_counter(
            TX_PATH
        )

        previous_time = time.monotonic()

        while True:
            time.sleep(
                SAMPLE_INTERVAL
            )

            current_time = time.monotonic()

            current_rx = self.read_counter(
                RX_PATH
            )

            current_tx = self.read_counter(
                TX_PATH
            )

            elapsed = (
                current_time -
                previous_time
            )

            if elapsed <= 0:
                continue

            rx_delta = current_rx - previous_rx
            tx_delta = current_tx - previous_tx

            if rx_delta < 0:
                rx_delta = 0

            if tx_delta < 0:
                tx_delta = 0

            rx_rate = (
                rx_delta * 8
            ) / elapsed

            tx_rate = (
                tx_delta * 8
            ) / elapsed

            with self.lock:
                self.rx_bytes = current_rx
                self.tx_bytes = current_tx

                self.rx_rate = rx_rate
                self.tx_rate = tx_rate

                self.rx_history.append(
                    rx_rate
                )

                self.tx_history.append(
                    tx_rate
                )

                if len(self.rx_history) > HISTORY_SIZE:
                    self.rx_history.pop(0)

                if len(self.tx_history) > HISTORY_SIZE:
                    self.tx_history.pop(0)

                if (
                    self.rx_min is None or
                    rx_rate < self.rx_min
                ):
                    self.rx_min = rx_rate

                if (
                    self.tx_min is None or
                    tx_rate < self.tx_min
                ):
                    self.tx_min = tx_rate

                self.rx_max = max(
                    self.rx_max,
                    rx_rate
                )

                self.tx_max = max(
                    self.tx_max,
                    tx_rate
                )

            previous_rx = current_rx
            previous_tx = current_tx
            previous_time = current_time

    def snapshot(self):
        with self.lock:
            rx_average = (
                sum(self.rx_history) /
                len(self.rx_history)
                if self.rx_history
                else 0
            )

            tx_average = (
                sum(self.tx_history) /
                len(self.tx_history)
                if self.tx_history
                else 0
            )

            return {
                "ok": True,
                "interface": INTERFACE,
                "ip": get_interface_ip(
                    INTERFACE
                ),
                "interfaces": get_interfaces(),

                "incoming": {
                    "current": self.rx_rate,
                    "average": rx_average,
                    "minimum": (
                        self.rx_min
                        if self.rx_min is not None
                        else 0
                    ),
                    "maximum": self.rx_max,
                    "total": self.rx_bytes,
                    "history": list(
                        self.rx_history
                    )
                },

                "outgoing": {
                    "current": self.tx_rate,
                    "average": tx_average,
                    "minimum": (
                        self.tx_min
                        if self.tx_min is not None
                        else 0
                    ),
                    "maximum": self.tx_max,
                    "total": self.tx_bytes,
                    "history": list(
                        self.tx_history
                    )
                }
            }


monitor = NetworkMonitor()


HTML = r"""
<!DOCTYPE html>
<html>

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>nload eth0</title>

<style>

* {
    box-sizing: border-box;
}

html,
body {
    width: 100%;
    height: 100%;

    margin: 0;
    padding: 0;

    background:
        #111;

    overflow: hidden;
}

body {
    display: flex;

    align-items: center;
    justify-content: center;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}

.window {
    width: 100vw;
    height: 100dvh;

    #max-width: 1800px;
    #max-height: 1200px;

    min-width: 700px;
    min-height: 0;

    display: flex;
    flex-direction: column;

    overflow: hidden;

    border-radius: 12px;

    background: #050505;

    border: 1px solid #3a3a3a;

    box-shadow:
        0 30px 80px rgba(0, 0, 0, 0.65),
        0 0 0 1px rgba(255, 255, 255, 0.04);
}

@media (max-width: 900px) {
    .window {
        width: 100dvw;
        height: 100dvh;

        min-width: 0;
        min-height: 0;

        border-radius: 10px;
    }

    .content {
        padding: 14px;
    }

    .stats {
        width: 190px;
        margin-left: 20px;
    }
}

@media (max-width: 650px) {
    .window {
        width: 100vw;
        height: 100dvh;

        min-width: 0;
        min-height: 0;

        border-radius: 8px;
    }

    .titlebar {
        height: 38px;
        min-height: 38px;
    }

    .traffic-lights {
        gap: 6px;
    }

    .light {
        width: 11px;
        height: 11px;
    }

    .content {
        padding: 10px;
        gap: 12px;
    }

    .stats {
        width: 175px;
        margin-left: 12px;

        font-size: 12px;
    }

    .graph,
    .device,
    .direction-title {
        font-size: 12px;
    }
}

.titlebar {
    height: 42px;

    flex-shrink: 0;

    display: flex;

    align-items: center;

    position: relative;

    padding: 0 14px;

    background:
        linear-gradient(
            #292929,
            #202020
        );

    border-bottom:
        1px solid
        #111;
}

.traffic-lights {
    display: flex;

    gap: 8px;
}

.light {
    width: 13px;
    height: 13px;

    border-radius: 50%;

    box-shadow:
        inset 0 1px 1px
        rgba(255,255,255,.35),
        0 0 1px
        rgba(0,0,0,.8);
}

.red {
    background: #ff5f57;
}

.yellow {
    background: #febc2e;
}

.green {
    background: #28c840;
}

.window-title {
    position: absolute;

    left: 50%;

    transform:
        translateX(-50%);

    color: #c8c8c8;

    font-size: 13px;

    font-weight: 500;

    pointer-events: none;
}

.content {
    flex: 1;

    min-height: 0;

    padding: 18px 22px 22px;

    display: flex;
    flex-direction: column;

    gap: 18px;

    overflow: hidden;

    background: #000;
}

.device {
    color: #00ff00;

    font-family:
        "DejaVu Sans Mono",
        "Liberation Mono",
        monospace;

    font-size: 14px;

    flex-shrink: 0;
}

.separator {
    color: #00ff00;

    overflow: hidden;

    white-space: pre;
}

.direction {
    flex: 1;

    min-height: 0;

    display: flex;
    flex-direction: column;

    color: #00ff00;

    font-family:
        "DejaVu Sans Mono",
        "Liberation Mono",
        monospace;
}

.direction-title {
    flex-shrink: 0;

    height: 22px;

    color: #00ff00;

    font-size: 14px;
}

.direction-body {
    flex: 1;

    min-height: 0;

    display: flex;

    align-items: stretch;
}

.graph-container {
    flex: 1;

    min-width: 0;
    min-height: 0;

    overflow: hidden;
}

.graph {
    width: 100%;
    height: 100%;

    margin: 0;
    padding: 0;

    color: #00ff00;

    font-family:
        "DejaVu Sans Mono",
        "Liberation Mono",
        monospace;

    font-size: 14px;

    line-height: 1.0;

    white-space: pre;

    overflow: hidden;
}

.stats {
    flex-shrink: 0;

    width: 230px;

    margin-left: 35px;

    display: flex;
    flex-direction: column;

    justify-content: flex-end;

    padding-bottom: 2px;

    color: #00ff00;

    font-family:
        "DejaVu Sans Mono",
        "Liberation Mono",
        monospace;

    font-size: 14px;

    line-height: 1.35;

    white-space: pre;
}

.stat {
    height: 19px;

    white-space: nowrap;
}

@media (
    max-width: 900px
) {

    .window {
        width: 100dvw;
        height:100dvh;

        min-width: 0;
        min-height: 0;
    }

    .content {
        padding: 14px;
    }

    .stats {
        width: 190px;
        margin-left: 20px;
    }

}

@media (
    max-width: 650px
) {

    .window {
        width: 100dvw;
        height: 100dvh;

        border-radius: 8px;
    }

    .stats {
        width: 175px;
        margin-left: 12px;

        font-size: 12px;
    }

    .graph,
    .device,
    .direction-title {
        font-size: 12px;
    }

}

</style>

</head>

<body>

<div class="window">

    <div class="titlebar">

        <div class="traffic-lights">
            <div class="light red"></div>
            <div class="light yellow"></div>
            <div class="light green"></div>
        </div>

        <div
            class="window-title"
            id="window-title"
        >
            nload eth0
        </div>

    </div>

    <div class="content">

        <div class="device">
            <div id="device"></div>
            <div
                class="separator"
                id="separator"
            ></div>
        </div>

        <div class="direction">

            <div class="direction-title">
                Incoming:
            </div>

            <div class="direction-body">

                <div class="graph-container">
                    <pre
                        class="graph"
                        id="incoming-graph"
                    ></pre>
                </div>

                <div class="stats">

                    <div
                        class="stat"
                        id="incoming-current"
                    ></div>

                    <div
                        class="stat"
                        id="incoming-average"
                    ></div>

                    <div
                        class="stat"
                        id="incoming-minimum"
                    ></div>

                    <div
                        class="stat"
                        id="incoming-maximum"
                    ></div>

                    <div
                        class="stat"
                        id="incoming-total"
                    ></div>

                </div>

            </div>

        </div>

        <div class="direction">

            <div class="direction-title">
                Outgoing:
            </div>

            <div class="direction-body">

                <div class="graph-container">
                    <pre
                        class="graph"
                        id="outgoing-graph"
                    ></pre>
                </div>

                <div class="stats">

                    <div
                        class="stat"
                        id="outgoing-current"
                    ></div>

                    <div
                        class="stat"
                        id="outgoing-average"
                    ></div>

                    <div
                        class="stat"
                        id="outgoing-minimum"
                    ></div>

                    <div
                        class="stat"
                        id="outgoing-maximum"
                    ></div>

                    <div
                        class="stat"
                        id="outgoing-total"
                    ></div>

                </div>

            </div>

        </div>

    </div>

</div>


<script>

const incomingGraph =
    document.getElementById(
        "incoming-graph"
    );

const outgoingGraph =
    document.getElementById(
        "outgoing-graph"
    );


function formatRate(value) {

    if (
        value >= 1000000000
    ) {
        return (
            (
                value /
                1000000000
            ).toFixed(2) +
            " GBit/s"
        );
    }

    if (
        value >= 1000000
    ) {
        return (
            (
                value /
                1000000
            ).toFixed(2) +
            " MBit/s"
        );
    }

    if (
        value >= 1000
    ) {
        return (
            (
                value /
                1000
            ).toFixed(2) +
            " KBit/s"
        );
    }

    return (
        value.toFixed(2) +
        " Bit/s"
    );
}


function formatBytes(value) {

    if (
        value >= 1000000000000
    ) {
        return (
            (
                value /
                1000000000000
            ).toFixed(2) +
            " TByte"
        );
    }

    if (
        value >= 1000000000
    ) {
        return (
            (
                value /
                1000000000
            ).toFixed(2) +
            " GByte"
        );
    }

    if (
        value >= 1000000
    ) {
        return (
            (
                value /
                1000000
            ).toFixed(2) +
            " MByte"
        );
    }

    if (
        value >= 1000
    ) {
        return (
            (
                value /
                1000
            ).toFixed(2) +
            " KByte"
        );
    }

    return (
        value.toFixed(0) +
        " Byte"
    );
}


function characterSize(element) {

    const style =
        getComputedStyle(
            element
        );

    const canvas =
        document.createElement(
            "canvas"
        );

    const context =
        canvas.getContext(
            "2d"
        );

    context.font =
        style.font;

    const width =
        context.measureText(
            "M"
        ).width;

    let lineHeight =
        parseFloat(
            style.lineHeight
        );

    if (
        Number.isNaN(
            lineHeight
        )
    ) {
        lineHeight = 14;
    }

    return {
        width: width,
        height: lineHeight
    };
}


function graphSize(element) {

    const chars =
        characterSize(
            element
        );

    return {
        cols: Math.max(
            1,
            Math.floor(
                element.clientWidth /
                chars.width
            )
        ),

        rows: Math.max(
            1,
            Math.floor(
                element.clientHeight /
                chars.height
            )
        )
    };
}


function resample(
    history,
    width
) {
    if (
        width <= 0
    ) {
        return [];
    }

    if (
        !history ||
        history.length === 0
    ) {
        return Array(
            width
        ).fill(0);
    }

    if (
        history.length === width
    ) {
        return history.slice();
    }

    const result = [];

    for (
        let x = 0;
        x < width;
        x++
    ) {
        const position =
            (
                x /
                Math.max(
                    1,
                    width - 1
                )
            ) *
            (
                history.length - 1
            );

        const left =
            Math.floor(
                position
            );

        const right =
            Math.min(
                history.length - 1,
                left + 1
            );

        const fraction =
            position - left;

        result.push(
            history[left] *
            (1 - fraction) +
            history[right] *
            fraction
        );
    }

    return result;
}


function createGraph(
    history,
    width,
    height
) {
    const graph = [];

    for (
        let y = 0;
        y < height;
        y++
    ) {
        graph.push(
            Array(
                width
            ).fill(" ")
        );
    }

    if (
        width <= 0 ||
        height <= 0
    ) {
        return graph;
    }

    const values =
        resample(
            history,
            width
        );

    let maximum = 1;

    for (
        const value of values
    ) {
        maximum =
            Math.max(
                maximum,
                value
            );
    }

    for (
        let x = 0;
        x < width;
        x++
    ) {
        const value =
            values[x];

        const level =
            (
                value /
                maximum
            ) *
            height;

        const full =
            Math.floor(
                level
            );

        const fraction =
            level -
            full;

        for (
            let y = 0;
            y < full;
            y++
        ) {
            const row =
                height -
                1 -
                y;

            if (
                row >= 0 &&
                row < height
            ) {
                graph[row][x] =
                    "#";
            }
        }

        if (
            full < height
        ) {
            const row =
                height -
                1 -
                full;

            if (
                row >= 0 &&
                row < height
            ) {
                if (
                    fraction >= 0.75
                ) {
                    graph[row][x] =
                        "#";
                } else if (
                    fraction >= 0.5
                ) {
                    graph[row][x] =
                        "|";
                } else if (
                    fraction >= 0.25
                ) {
                    graph[row][x] =
                        ".";
                }
            }
        }
    }

    return graph;
}


function renderGraph(
    element,
    history
) {
    const size =
        graphSize(
            element
        );

    const graph =
        createGraph(
            history,
            size.cols,
            size.rows
        );

    element.textContent =
        graph
            .map(
                row =>
                    row.join("")
            )
            .join("\n");
}


function renderStats(
    prefix,
    data
) {
    document.getElementById(
        prefix + "-current"
    ).textContent =
        "Curr: " +
        formatRate(
            data.current
        );

    document.getElementById(
        prefix + "-average"
    ).textContent =
        "Avg:  " +
        formatRate(
            data.average
        );

    document.getElementById(
        prefix + "-minimum"
    ).textContent =
        "Min:  " +
        formatRate(
            data.minimum
        );

    document.getElementById(
        prefix + "-maximum"
    ).textContent =
        "Max:  " +
        formatRate(
            data.maximum
        );

    document.getElementById(
        prefix + "-total"
    ).textContent =
        "Ttl:  " +
        formatBytes(
            data.total
        );
}


function render(data) {

    const interfaces =
        data.interfaces || [];

    const index =
        interfaces.indexOf(
            data.interface
        );

    //const interfaceNumber =
    //    index >= 0
    //        ? index + 1
    //        : 1;

    //const interfaceCount =
    //    Math.max(
    //        1,
    //        interfaces.length
    //    );

    const interfaceNumber = 1;
    const interfaceCount = 1;

    document.getElementById(
        "device"
    ).textContent =
        "Device " +
        data.interface +
        " [" +
        data.ip +
        "] (" +
        interfaceNumber +
        "/" +
        interfaceCount +
        "):";

    const separator =
        document.getElementById(
            "separator"
        );

    const separatorWidth =
        Math.max(
            1,
            Math.floor(
                separator.clientWidth /
                characterSize(
                    separator
                ).width
            )
        );

    separator.textContent =
        "=".repeat(
            separatorWidth
        );

    renderGraph(
        incomingGraph,
        data.incoming.history
    );

    renderGraph(
        outgoingGraph,
        data.outgoing.history
    );

    renderStats(
        "incoming",
        data.incoming
    );

    renderStats(
        "outgoing",
        data.outgoing
    );
}

let polling = false;

async function poll() {

    if (
        polling
    ) {
        return;
    }

    polling = true;

    try {

        const response =
            await fetch(
                "/api/stats",
                {
                    method: "GET",
                    cache: "no-store"
                }
            );

        if (
            !response.ok
        ) {
            throw new Error(
                "HTTP " +
                response.status
            );
        }

        const data =
            await response.json();

        if (
            data.ok
        ) {
            render(data);
        }

    } catch (
        error
    ) {
    }

    polling = false;

    setTimeout(
        poll,
        1000
    );
}


let resizeTimer = null;


window.addEventListener(
    "resize",
    function() {

        clearTimeout(
            resizeTimer
        );

        resizeTimer =
            setTimeout(
                poll,
                50
            );
    }
);


poll();

</script>

</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(
        HTML
    )


@app.route("/api/stats")
def api_stats():
    return jsonify(
        monitor.snapshot()
    )


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        threaded=True
    )
