/**
 * packet-selection/packet-selection-template.js:
 * 
 * Widget for selecting packets of a specific file for downlink.
 * 
 */

export let packet_selection_template = `
<transition name="fade">
    <div class="alert alert-warning" role="alert">
        <h3>Uplink File Packet List</h3>
        <h4>Selecting Packets for: {{ selected.source }}</h4>
        <label for="packetList">Enumerate specific file packets to uplink in a comma-separated list</label>
        <textarea id="packetList" class="col-md-12" @input="validate"
            v-model="packetInput"
            :class="error == '' ? '' : 'is-invalid'"
            placeholder="List specific packets to uplink: 1, 5, 9..."></textarea>
        <div class="invalid-feedback">{{ error }}</div>
        <div class="form-row">
            <!-- Spacer: intentionally empty -->
            <div class="col-md-8"></div>
            <div class="col-md-4">
                <button type="button" class="btn btn-primary btn-block"
                        v-on:click="save" title="Save" :disabled="error != ''"
                >
                    <span class="d-md-none d-lg-inline">Save</span>
                </button>
            </div>
        </div>
    </div>
</transition>

`;