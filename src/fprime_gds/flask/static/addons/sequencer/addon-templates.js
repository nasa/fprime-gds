export let sequencer_template = `
    <div class="fp-flex-repeater">
        <div class="fp-flex-header">
            <h2>Command Sequencer</h2>
            <form v-on:submit.prevent="() => { return false;}" class="was-validated" novalidate>
                <div class="form-group row">
                    <label class="col-1 col-form-label" for="sequence">Name</label>
                    <div class="col-4" for="sequence">
                        <input type="text" id="sequence" class="form-control" v-model="sequence.name" :disabled="active"
                               pattern="[^;\\\\\\/]+\\.seq" placeholder="Sequence name ending in .seq" required/>
                        <div class="invalid-feedback">{{ (messages.error) ? messages.error : "Supply filename ending with .seq" }}</div>
                    </div>
                    <div class="col col-4">
                        <label for="sequenceUpload">Upload sequence file:</label>
                        <input type="file" id="sequenceUpload" accept=".seq"
                               v-on:change="setSequence($event.target.files[0])">
                    </div>
                    <div class="col col-3">
                        <button class="btn btn-primary float-right" :disabled="active" v-on:click="sendSequence(true)">Uplink</button>
                        <button class="btn btn-secondary float-right" v-on:click="builder = !builder">Command Builder</button>
                        <button class="btn btn-secondary float-left" :disabled="active" v-on:click="download">Download</button>
                    </div>
                </div>
            </form>
        </div>
        <transition name="fade">
            <div class="alert alert-warning" role="alert" v-show="builder">
                <h4>Command Builder</h4>
                <command-input :builder="true"></command-input>
            </div>
        </transition>
        
        <div class="fp-scroll-container">
            <div class="code-parent fp-scrollable"></div>
        </div>
        <div class="fp-flex-header">
            <textarea class="form-control" id="out" style="height:100%" v-model="messages.validation" readonly></textarea>            
        </div>
        <small class="form-text text-muted">
        Sequence compilation output
        </small>
    </div>
`;