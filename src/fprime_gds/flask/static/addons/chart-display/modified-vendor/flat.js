/**
 * BSD 3-Clause "New" or "Revised" License
 * Source: https://github.com/hughsk/flat
 * Copyright (c) 2014, Hugh Kennedy

The module has been modified to support F Prime GDS tasks
*/

function isBuffer(obj) {
    return (
        obj &&
        obj.constructor &&
        typeof obj.constructor.isBuffer === "function" &&
        obj.constructor.isBuffer(obj)
    );
}

function keyIdentity(key) {
    return key;
}

/**
 *
 * @param {json} target : channel object
 * @param {json} opts : config options
 * @returns list of flatten paths
 */
function flatten(target, opts) {
    opts = opts || {};
    // Default supported F Prime types
    const supportedTypes =
        ["U8", "U16", "U32", "U64", "I8", "I16", "I32", "I64", "F32", "F64"] ||
        opts.supportedTypes;

    const prefix = opts.prefix || "";
    const delimiter = opts.delimiter || ".";
    const maxDepth = opts.maxDepth;
    const transformKey = opts.transformKey || keyIdentity;
    const output = {};

    function step(object, prev, currentDepth) {
        currentDepth = currentDepth || 1;

        Object.keys(object).forEach(function (key) {
            const value = object[key];
            const isarray = opts.safe && Array.isArray(value);
            const type = Object.prototype.toString.call(value);
            const isbuffer = isBuffer(value);
            const isobject =
                type === "[object Object]" || type === "[object Array]";

            const newKey = prev
                ? prev + delimiter + transformKey(key)
                : transformKey(key);

            if (
                !isarray &&
                !isbuffer &&
                isobject &&
                Object.keys(value).length &&
                (!opts.maxDepth || currentDepth < maxDepth)
            ) {
                return step(value, newKey, currentDepth + 1);
            }

            if (supportedTypes.indexOf(value) !== -1) {
                let keyId = "";
                if (prefix) {
                    keyId = keyId.concat(prefix, delimiter, newKey);
                } else {
                    keyId = newKey;
                }
                output[keyId] = value;
            }
        });
    }

    step(target);

    // Get unique parent of each path
    const output_set = new Set();
    for (const [key, value] of Object.entries(output)) {
        output_set.add(key.split(delimiter).slice(0, -1).join(delimiter));
    }

    // Sort and return a list of flatten json paths
    let output_list = Array.from(output_set).sort();
    return output_list;
}

export { flatten };
