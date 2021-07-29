/**
 * Contains the functions and definitions needed for handling sibling charts and the syncing between them.
 */


/**
 * Syncronize the axis of the supplied leader to the supplied follower
 * @param leader: source of axis information
 * @param follower: destination of axis information
 */
function syncSibling(leader, follower) {
    const {min, max} = leader.scales.x;
    follower.zoomScale("x", {min: min, max: max}, "none");
}


export class SiblingSet {

    constructor() {
        this.in_sync = false;
        this._siblings = [];

        this.pause = this.get_guarded_function(this.__pauseAll);
        this.reset = this.get_guarded_function(this.__resetAll);
        this.syncToAll = this.get_guarded_function((input) => {this.__syncToAll(input.chart)});
        this.sync = this.get_guarded_function(this.__syncFromPrime);
    }

    get_guarded_function(func) {
        let _self = this;
        return (...args) => {
            if (_self.in_sync) {
                func.apply(_self, args);
            }
        };
    }

    __syncFromPrime(sibling) {
        let prime = this.prime();
        if (sibling == null || prime == null || prime == sibling) {
            return;
        }
        syncSibling(this.prime(), sibling);
    }

    __syncToAll(leader) {
        let syncing_function = syncSibling.bind(undefined, leader);
        if (leader == null) {
            return;
        }
        this._siblings.filter((item) => {return item !== leader}).map(syncing_function);
    }

    __pauseAll(pause) {
        this._siblings.map((sibling) => {sibling.options.scales.x.realtime.pause = pause;});
    }

    __resetAll() {
        this._siblings.map((sibling) => {sibling.resetZoom("none")});
    }

    prime() {
        return (this._siblings) ? this._siblings[0] : null;
    }

    add(sibling) {
        if (this._siblings.indexOf(sibling) === -1) {
            this._siblings.push(sibling);
        }
    }
    remove(sibling) {
        let index = this._siblings.indexOf(sibling);
        if (index !== -1) {
            this._siblings.slice(index, 1);
        }
    }
}