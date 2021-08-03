/**
 * sibling.js:
 *
 * Contains the functions and definitions needed for handling sibling charts and the syncing between them.
 */


/**
 * Synchronize the axis of the supplied leader to the supplied follower
 * @param leader: source of axis information
 * @param follower: destination of axis information
 */
function syncSibling(leader, follower) {
    const {min, max} = leader.scales.x;
    follower.zoomScale("x", {min: min, max: max}, "none");
}

/**
 * SiblingSet:
 *
 * A class containing a set of siblings that will be synchronized together. These siblings will share time and axis
 * bounds when the lock axis is set.  Note: a sibling is a Chart JS object.
 */
export class SiblingSet {
    constructor() {
        this.in_sync = false;
        this._siblings = [];

        this.pause = this.get_guarded_function(this.__pauseAll);
        this.reset = this.get_guarded_function(this.__resetAll);
        this.syncToAll = this.get_guarded_function((input) => {this.__syncToAll(input.chart)});
        this.sync = this.get_guarded_function(this.__syncFromPrime);
    }

    /**
     * Provides a function guarded with an "in_sync" check. This ensures that the functions only run when we want the
     * charts to be synchronized.
     * @param func: function to produce a guarded variant of
     * @return {Function}: function, but only run when not in sync.
     */
    get_guarded_function(func) {
        let _self = this;
        return (...args) => {
            if (_self.in_sync) {
                func.apply(_self, args);
            }
        };
    }

    /**
     * Synchronizes the supplied sibling to the primary sibling as returned by the prime() function of this class.
     * @param sibling: sibling who will change to conform to the parent sibling
     * @private
     */
    __syncFromPrime(sibling) {
        let prime = this.prime();
        if (sibling == null || prime == null || prime === sibling) {
            return;
        }
        syncSibling(this.prime(), sibling);
    }

    /**
     * Synchronize the given leader to all siblings.
     * @param leader: leader to use as base for conforming others
     * @private
     */
    __syncToAll(leader) {
        let syncing_function = syncSibling.bind(undefined, leader);
        if (leader == null) {
            return;
        }
        this._siblings.filter((item) => {return item !== leader}).map(syncing_function);
    }

    /**
     * Pause all siblings by setting their pause member variable.
     * @param pause: true/false to pause or not pause.
     * @private
     */
    __pauseAll(pause) {
        this._siblings.map((sibling) => {sibling.options.scales.x.realtime.pause = pause;});
    }

    /**
     * Reset the zoom level of all siblings.
     * @private
     */
    __resetAll() {
        this._siblings.map((sibling) => {sibling.resetZoom("none")});
    }

    /**
     * Returns the prime sibling.  This is the first of the siblings in the list, or null if no siblings exist.
     * @return {null}: prime sibling or null
     */
    prime() {
        return (this._siblings.length > 0) ? this._siblings[0] : null;
    }

    /**
     * Add a sibling to the set
     * @param sibling: sibling to add
     */
    add(sibling) {
        if (this._siblings.indexOf(sibling) === -1) {
            this._siblings.push(sibling);
        }
    }

    /**
     * Remove sibling from set
     * @param sibling: sibling to remove
     */
    remove(sibling) {
        let index = this._siblings.indexOf(sibling);
        if (index !== -1) {
            this._siblings.splice(index, 1); 
        }
    }
}
