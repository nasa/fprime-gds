import {sequencer_template} from "./addon-templates.js";
import {_loader} from "../../js/loader.js";
import {_datastore} from "../../js/datastore.js";

import {basicSetup, EditorState, EditorView, linter} from "./third/code-mirror.es.js"

import {sequenceLanguageSupport} from "./autocomplete.js"

const LINE_REG = /Line\s*(\d+):/;
const LINE_END = /\r?\n/;
const LINT_SRC = "Sequence Checker";





function buildDiagnostic(view, line) {
    let diagnostic = {severity: "error", message: line, source: LINT_SRC, from:0, to:0};

    try {
        let match = line.match(LINE_REG);
        if (match != null) {
            let line_number = parseInt(match[1]);
            let line = view.state.doc.line(line_number);
            Object.assign(diagnostic, {from: line.from, to:line.to});
        }
    } catch (e) {
        console.error("Linting system error:" + e.toString());
    }
    return diagnostic;
}


function process(view, response) {
    let parsed = JSON.parse(response);
    let message = parsed.message.error || parsed;
    let type = parsed.message.type || "error";

     let lines = message.split(LINE_END).map((line) => {return line.trim()}).filter((line) => {return line != ""});
     return lines.map(buildDiagnostic.bind(undefined, view));
}




function lintMaster(view) {
    let code = view.state.doc.toString();
    return new Promise((resolve) => {
        _loader.load("/sequence", "PUT",
            {
                "key": 0xfeedcafe,
                "name": ".__tmp_lint.seq",
                "text": code,
                "uplink": "false"
            }
        ).then(
            (response) => {
                resolve([])
            }
        ).catch(
            (response) => {
                resolve(process(view, response))
            }
        );
    });
}

Vue.component("sequencer", {
    data: function () {
        return {
            view: null,
            sequence: {
                name: "",
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
    mounted: function() {
        let parent = this.$el.getElementsByClassName("code-parent")[0];
        this.view = new EditorView({
            state: EditorState.create({extensions: [basicSetup, sequenceLanguageSupport(_datastore.commands),
                                                    linter(lintMaster)]}),
            parent: parent
        });
    },
    template: sequencer_template,
    methods: {
        setSequence(file) {
            const fileReader = new FileReader();
            const _self = this;
            fileReader.onload = function(event) {
                const file_text = event.target.result;
                _self.sequence.name = file.name;
                _self.view.dispatch({changes: {from: 0, to: _self.view.state.doc.length, insert: file_text}});
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
                    "text": this.view.state.doc.toString(),
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
        },
        download() {
            if (this.sequence.name === "" || this.view === null) {
                return;
            }
            // Create a magic hidden anchor and click it to download.
            let element = document.createElement('a');
            element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(this.view.state.doc.toString()));
            element.setAttribute('download', this.sequence.name);
            element.style.display = 'none';
            document.body.appendChild(element);
            element.click();
            document.body.removeChild(element);
        }
    },
});