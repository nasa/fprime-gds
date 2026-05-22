/**
 * Sequencer Plugin:
 *
 * The primary entry point for the sequencer plugin.  This plugin provides a sequence editor, validation, and uplink
 * integration for fprime sequences. It provides a Vue component that is embedded using the `<sequencer></sequencer>`
 * tag pair. It does not require any input bindings to the plugin.
 *
 * The plugin depends on the `_datastore` singleton for command dictionaries and then `_loader` singleton used to
 * uplink sequences via the `/sequence` endpoint.
 */
import {sequencer_template} from "./addon-templates.js";
import {_loader} from "../../js/loader.js";
import {_datastore} from "../../js/datastore.js";

// Language editor and support
import {basicSetup, EditorState, EditorView, linter} from "./third/code-mirror.es.js"
import {sequenceLanguageSupport} from "./autocomplete.js"
import {processResponse} from "./lint.js";
import { SaferParser } from "../../js/json.js";
SaferParser.register();

/**
 * Sequence sender function used to uplink the sequence and return a promise of how to handle the server's return.
 * @param view: view to mine for sequence content.
 * @param filename: filename of sequence to send
 * @param uplink: uplink true/false
 * @param processor: message processor before resolving promise
 * @return {Promise<unknown>}
 */
function sequence_sender(view, filename, uplink, processor, destination) {
    let code = view.state.doc.toString();
    return new Promise((resolve) => {
        let func = processor || ((message) => message);
        let handler = (response) => {
            let parsed = response;
            try {
                parsed = JSON.parse(parsed);
            } catch {
                parsed = response;
            }
            parsed = parsed.message || parsed;
            resolve(func(parsed));
        };
        let payload = {
            "key": 0xfeedcafe,
            "name": filename,
            "text": code,
            "uplink": (uplink ? uplink : false).toString()
        };
        if (destination) {
            payload["destination"] = destination;
        }
        _loader.load("/sequence", "PUT", payload).then(handler).catch(handler);
    });
}

/**
 * Sequencer component used to represent the composition and editing of sequences.
 */
Vue.component("sequencer", {
    template: sequencer_template,
    data() {
        return {
            view: null,
            sequence: {name: ""},
            destination: "",
            lastUplinkedSequence: null,
            messages: {
                validation: "",
                error: ""
            },
            active: false,
            builder: false,
        };
    },
    /**
     * When the Vue component is mounted, we construct an editor to replace the content of the code-parent div.
     */
    mounted() {
        let parent = this.$el.getElementsByClassName("code-parent")[0];
        let linter_func = (view) => sequence_sender(view, "._temp.seq", false,
            (message) => processResponse(view, message));
        this.view = new EditorView({
            state: EditorState.create({extensions: [basicSetup, sequenceLanguageSupport(_datastore.commands),
                                                    linter(linter_func)]}),
            parent: parent
        });
        _loader.load("/sequence").then((data) => {
            if (data && data.destination) {
                this.destination = data.destination;
            }
        }).catch(() => {});
    },
    methods: {
        /**
         * Used when uploading a sequence file to set the editor's content.
         * @param file: file object from upload.
         */
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
        /**
         * Method used to send the sequence for uplink purposes. Responses from the server a processed and posted in the
         * output box below the editor.
         */
        sendSequence() {
            let _self = this;
            this.active = true;
            this.messages.validation = "";
            this.messages.error = "";
            let dest = this.destination || null;
            sequence_sender(this.view, this.sequence.name, true, null, dest).then((message) => {
                _self.active = false;
                let type = message.type || "validation";
                let content = message.error || message;
                _self.messages[type] = content;
                if (type !== "error") {
                    let binName = _self.sequence.name.replace(/\.seq$/, ".bin");
                    let dir = _self.destination || "/seq";
                    _self.lastUplinkedSequence = dir.replace(/\/$/, "") + "/" + binName;
                }
            });
        },
        /**
         * Sends a CS_RUN command for the last uplinked sequence.
         */
        runSequence() {
            if (!this.lastUplinkedSequence) {
                return;
            }
            let _self = this;
            let command = this.findCsRunCommand();
            if (!command) {
                this.messages.error = "CS_RUN command not found in dictionary. Cannot run sequence.";
                return;
            }
            this.active = true;
            this.messages.validation = "";
            this.messages.error = "";
            _loader.load("/commands/" + encodeURIComponent(command), "PUT", {
                "key": "0xfeedcafe",
                "arguments": [this.lastUplinkedSequence, "BLOCK"]
            }).then(() => {
                _self.active = false;
                _self.messages.validation = "Sent CS_RUN for " + _self.lastUplinkedSequence;
            }).catch((error) => {
                _self.active = false;
                try {
                    let parsed = JSON.parse(error);
                    _self.messages.error = parsed.message || error;
                } catch {
                    _self.messages.error = error || "Failed to send CS_RUN command";
                }
            });
        },
        /**
         * Finds the CS_RUN command mnemonic from the command dictionary.
         */
        findCsRunCommand() {
            for (let key in _datastore.commands) {
                if (key.endsWith(".CS_RUN") || key === "CS_RUN") {
                    return key;
                }
            }
            return null;
        },
        /**
         * Download button action used to generate file data from the editor and supply it as a file downloading to the
         * user's computer.
         */
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
