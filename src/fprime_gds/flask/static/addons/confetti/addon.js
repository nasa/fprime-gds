import { _datastore } from "../../js/datastore.js";
import { tsParticles } from "../../third-party/js/tsparticles-v3.9.1.engine.esm.js";

// TODO(nateinaction): Make this work offline with local files
import { loadAll } from "https://cdn.jsdelivr.net/npm/@tsparticles/all@3.9.1/+esm";
// import { loadAll } from "../../third-party/js/tsparticles-v3.9.1.all.bundle.esm.js";

// Simple confetti addon: watches the datastore flags and triggers confetti
Vue.component("confetti-trigger", {
    data() {
        return {
            hasTriggered: false,
            flags: _datastore.flags,
        };
    },
    created() {
        // Watch for any active_ flag to go true by polling orb-like logic
        this.unwatch = this.$watch(
            () => {
                let orb = false;
                for (let key in this.flags) {
                    orb = orb || (key.startsWith("active_") && this.flags[key]);
                }
                return orb;
            },
            (newVal, oldVal) => {
                if (newVal && !this.hasTriggered) {
                    this.triggerConfetti();
                    this.hasTriggered = true;
                }
            }
        );
    },
    beforeDestroy() {
        if (this.unwatch) this.unwatch();
    },
    methods: {
        triggerConfetti() {

            const confettiEmitter = (direction, position) => {
                return {
                    life: {
                        count: 1,
                        duration: 2,
                    },
                    direction,
                    rate: {
                        quantity: 25,
                        delay: 0.2
                    },
                    position
                };
            };

            const options = {
                particles: {
                    angle: {
                        value: 0,
                        offset: 30
                    },
                    move: {
                        enable: true,
                        outModes: {
                            top: "none",
                            default: "destroy"
                        },
                        gravity: {
                            enable: true
                        },
                        speed: { min: 2, max: 20 },
                        decay: 0.01
                    },
                    number: {
                        value: 0,
                        limit: 300
                    },
                    opacity: {
                        value: 1
                    },
                    color: {
                    value: [
                        "#00FFFC",
                        "#FC00FF",
                        "#fffc00",
                    ]
                    },
                    shape: {
                        type: [
                            "circle",
                            "square",
                            "triangle",
                        ],
                    },
                    size: {
                        value: { min: 2, max: 6 },
                        animation: {
                            count: 1,
                            startValue: "max",
                            destroy: "min",
                            enable: true,
                            speed: 0.01,
                            sync: true
                        }
                    },
                    rotate: {
                        value: {
                            min: 0,
                            max: 360
                        },
                        direction: "random",
                        animation: {
                            enable: true,
                            speed: 60
                        }
                    },
                    tilt: {
                        direction: "random",
                        enable: true,
                        value: {
                            min: 0,
                            max: 360
                        },
                        animation: {
                            enable: true,
                            speed: 60
                        }
                    },
                    roll: {
                        darken: {
                            enable: true,
                            value: 25
                        },
                        enable: true,
                        speed: {
                            min: 15,
                            max: 25
                        }
                    },
                    wobble: {
                        distance: 30,
                        enable: true,
                        speed: {
                            min: -15,
                            max: 15
                        }
                    }
                },
                emitters: [
                    confettiEmitter("top-right", { x: 0, y: 0 }),
                    confettiEmitter("top-center", { x: 25, y: 0 }),
                    confettiEmitter("top-center", { x: 50, y: 0 }),
                    confettiEmitter("top-center", { x: 75, y: 0 }),
                    confettiEmitter("top-left", { x: 100, y: 0 })
                ]
            };

            tsParticles.load({
                id: "tsparticles",
                options: options,
            });
        }
    }
});

await loadAll(tsParticles);

// Create a hidden element instance so the component is mounted and watcher runs
const mountEl = document.createElement("div");
mountEl.id = "tsparticles";
mountEl.style.display = "none";
document.body.appendChild(mountEl);
new Vue({ el: mountEl, template: "<confetti-trigger></confetti-trigger>" });
