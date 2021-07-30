import {sequencer_template} from "./addon-templates.js";
import {_loader} from "../../js/loader.js";

function modify_paste(paste, skip=false) {
    let lines = paste.split(/\r?\n/);
    for (let i = (skip) ? 0 : 1; i < lines.length; i++) {
        let line = lines[i];
        if (line != "" && line[0] != ';' && !line.match(/^R\d{2}:\d{2}:\d{2}(.\d{3})?[, ]?.*/)) {
            lines[i] = "R00:00:00.000 " + line;
        }
    }
    return lines.join("\n");
}

Vue.component("sequencer", {
    data: function () {
        return {
            sequence: {
                name: "",
                text: "; Input sequence here\nR00:00:00 cmdDisp.CMD_NO_OP",
            },
            messages: {
                validation: "",
                error: ""
            },
            active: false,
            builder: false,
            // Paste temporary variables
            previous: "",
            paste: ""
        };
    },
    template: sequencer_template,
    methods: {
        onPaste(event) {
            let paste = (event.clipboardData || window.clipboardData).getData('text');
            this.previous = this.sequence.text;
            this.paste = paste;
        },
        setSequence(file) {
            const fileReader = new FileReader();
            const _self = this;
            fileReader.onload = function(event) {
                const file_text = event.target.result;
                _self.sequence.text = file_text;
                _self.sequence.name = file.name;
            };
            fileReader.readAsText(file);
        },
        sendSequence(uplink) {
            let _self = this;
            this.active = true;
            this.messages.validation = "";
            this.messages.error = "";
            _loader.load("/sequence", "PUT",
                {
                    "key": 0xfeedcafe,
                    "name": this.sequence.name,
                    "text": this.sequence.text,
                    "uplink": uplink ? "true" : "false"
                }
            ).then(function(response) {
                _self.active = false;
                let message = response.message || "No server response";
                _self.messages.validation = message;
            })
            .catch(function(response) {
                _self.active = false;
                let parsed = JSON.parse(response);
                let message = parsed.message.error || parsed;
                let type = parsed.message.type || "error";
                _self.messages[type] = message;
            });
        }
    },
});