import { _datastore } from "../../js/datastore.js";
import { tsParticles } from "../../third-party/js/tsparticles-v3.9.1.engine.esm.js";
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
            tsParticles.load({
                id: "tsparticles",
                options: {
                    "fullScreen": {
                        "zIndex": 1
                    },
                    "particles": {
                        "number": {
                        "value": 0
                        },
                        "color": {
                        "value": [
                            "#00FFFC",
                            "#FC00FF",
                            "#fffc00"
                        ]
                        },
                        "shape": {
                        "type": [
                            "circle",
                            "square",
                            "triangle"
                        ],
                        "options": {}
                        },
                        "opacity": {
                        "value": {
                            "min": 0,
                            "max": 1
                        },
                        "animation": {
                            "enable": true,
                            "speed": 2,
                            "startValue": "max",
                            "destroy": "min"
                        }
                        },
                        "size": {
                        "value": {
                            "min": 2,
                            "max": 4
                        }
                        },
                        "links": {
                        "enable": false
                        },
                        "life": {
                        "duration": {
                            "sync": true,
                            "value": 5
                        },
                        "count": 1
                        },
                        "move": {
                        "enable": true,
                        "gravity": {
                            "enable": true,
                            "acceleration": 10
                        },
                        "speed": {
                            "min": 10,
                            "max": 20
                        },
                        "decay": 0.1,
                        "direction": "none",
                        "straight": false,
                        "outModes": {
                            "default": "destroy",
                            "top": "none"
                        }
                        },
                        "rotate": {
                        "value": {
                            "min": 0,
                            "max": 360
                        },
                        "direction": "random",
                        "move": true,
                        "animation": {
                            "enable": true,
                            "speed": 60
                        }
                        },
                        "tilt": {
                        "direction": "random",
                        "enable": true,
                        "move": true,
                        "value": {
                            "min": 0,
                            "max": 360
                        },
                        "animation": {
                            "enable": true,
                            "speed": 60
                        }
                        },
                        "roll": {
                        "darken": {
                            "enable": true,
                            "value": 25
                        },
                        "enable": true,
                        "speed": {
                            "min": 15,
                            "max": 25
                        }
                        },
                        "wobble": {
                        "distance": 30,
                        "enable": true,
                        "move": true,
                        "speed": {
                            "min": -15,
                            "max": 15
                        }
                        }
                    },
                    "emitters": {
                        "life": {
                        "count": 1,
                        "duration": 0.1,
                        "delay": 0.4
                        },
                        "rate": {
                        "delay": 0.1,
                        "quantity": 150
                        },
                        "size": {
                        "width": 0,
                        "height": 0
                        }
                    }
                }
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
