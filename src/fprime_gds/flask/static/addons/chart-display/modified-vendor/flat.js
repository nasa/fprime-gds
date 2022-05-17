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
        ["U8Type", "U16Type", "U32Type", "U64Type", "I8Type", "I16Type", "I32Type", "I64Type", "F32Type", "F64Type"];

    const prefix = opts.prefix || "";
    const delimiter = opts.delimiter || ".";
    const maxDepth = opts.maxDepth;
    const transformKey = opts.transformKey || keyIdentity;
    const output = {};

    function step(object, prev, currentDepth) {
        currentDepth = currentDepth || 1;

        // Cannot handle strings and enumerations
        if (object.name.endsWith("String") || ("ENUM_DICT" in object)) {
            return;
        }
        else if ("LENGTH" in object) {
            let new_object = [...Array(object["LENGTH"])].map(() => { return {"name": object["MEMBER_TYPE"].name} });
            object = new_object;
        }
        else if ("MEMBER_LIST" in object) {
                let new_object = Object.fromEntries(Object.values(object.MEMBER_LIST).map((member) => [member[0], member[1]]))
                object = new_object;
        }
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
    for (const [key, _] of Object.entries(output)) {
        output_set.add(key.split(delimiter).slice(0, -1).join(delimiter));
    }

    // Sort and return a list of flatten json paths
    let output_list = Array.from(output_set).sort();
    return output_list;
}

export { flatten };
