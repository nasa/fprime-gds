/**
 * Autocomplete functions:
 *
 * These functions build on the language support adding inn contextual autocomplete from the commands dictionary.
 */
import {LanguageSupport, syntaxTree, sequenceLanguage, snippetCompletion} from "./third/code-mirror.es.js";

const match = /[a-zA-Z_0-9$.]+$/;
const span = /\w*$/;

/**
 * Takes inn a list of args and the current index. Generates a string template for the remaining arguments.
 * @param args: arguments list from command dictionary
 * @param index: index of the current argument
 * @return template string
 */
function get_args_template(args, index) {
    let suffix = index;
    return args.slice(index).map((arg) => arg.type.name).map(
        (item) => {
            return  "${" + item + "_" + suffix++ +"}";
        }).join(" ");
}

/**
 * Produces autocomplete results for the given command and argument index. This will allow for completing enumeration
 * values and argument specs.
 * @param command: command dictionary entry for current command. If null, the results will also be empty.
 * @param index: index of argument being handled.
 * @return {{options: *}}
 */
function results(command, index) {
    let args = (command || {args: []}).args;
    let options = [];
    if ((index < args.length) && ("ENUM_DICT" in args[index].type)) {
        options = Object.keys(args[index].type.ENUM_DICT).map((item) => {return {label: item}});
    }
    // Add snippet for remaining args
    let template = get_args_template(args, index);
    if (template !== "") {
        options.push(snippetCompletion(template, {label: "$ARGS"}));
    }
    return {options: options};
}

/**
 * Handle arg-local autocomplete. Detects active command from dictionary, argument's position in command's arguments,
 * and then calls for results based on these context properties.
 * @param commands: commands dictionary
 * @param node: active node being edited
 * @param siblings: right to left list of siblings
 * @param state: editor state (for reading current command)
 * @return {null|{options: *}}
 */
function autoArg(commands, node, siblings, state) {
    let matching = siblings.filter((sibling) => {return sibling.name === "Command"});
    // Check to make sure we found a command
    if (matching.length > 0) {
        let command = matching[0];
        command = state.doc.slice(command.from, command.to).toString();
        return results(commands[command], siblings.indexOf(matching[0]));
    }
    return null;
}

/**
 * Autocomplete routing function used to route autocomplete functions based on context of the auto-completion. In short
 * this function detects what position in the statement is being edited allowing positional autocomplete of various
 * items: time tag template, args (enum and args template), and full command names. Caller must set .from and .span
 * fields of the completion result before returning to editor.
 * @param commands: commands dictionary
 * @param node: current node being edited.  Should not be null, but can be of delimiter or other type.
 * @param siblings: list of siblings left of the node, used for context
 * @param state: context state used to read currently typed data
 * @return CompletionResult without the .from nor .span attributes or null
 */
function autocomplete(commands, node, siblings, state) {
    // Command handling done when the node is a command or the previous sibling is a time tag
    if (node.name === "Command" || ((siblings.length > 0) && siblings[0].name === "TimeTag") ) {
        return {options: Object.keys(commands).map((item) => {return {label: item}})};
    }
    else if (node.name === "Arg" || ((siblings.length > 0) && ["Command", "Arg"].indexOf(siblings[0].name) !== -1)) {
        return autoArg(commands, node, siblings, state);
    }
    else if (siblings.length === 0) {
        let snips = ["R${hours}:${minutes}:${seconds}", "A${year}-${doy}T${hours}:${minutes}:${seconds}"];
        return {options: snips.map((item) => {return snippetCompletion(item, {label: item})})};
    }
    return null;
}

/**
 * Find the parent of the given node as long as it matches one of the given types. Returns null if no such parent
 * exists. Node must come from a complete language tree parsing and may be returned as "parent" in the case it is of
 * matching type.
 * @param node: node to search for matching parent
 * @param types: types of matching parents to find
 * @return first parent, including node, whose type is in types or null
 */
function matching_node_parent(node, types) {
    let parent = node;
    while (parent != null && types.indexOf(parent.name) === -1) {
        parent = parent.parent;
    }
    return parent;
}

/**
 * Function used to generate a list of left siblings of the parsed language tree as long as they are of one of the
 * supplied types. This list is left to right ordered and not including the node nor any right siblings.
 * @param node: node from which to generate matching siblings
 * @param types: types of siblings permitted. Others will be ignored.
 * @return {[]}: list of sibling nodes
 */
function sibling_list(node, types) {
    let siblings = [];
    node = node.prevSibling;
    while (node != null) {
        let current = matching_node_parent(node, types);
        if (current != null) {
            siblings.push(current);
            node = current;
        }
        node = node.prevSibling;
    }
    return siblings;

}

/**
 * Auto completion builder function. This returns a "auto complete" function taking in an autocomplete context and
 * returning a autocomplete result. Will handle both as-typed and on request completions matching and replacing back
 * to the nearest non-word, non-".", non-"$" word where "$" is used for autocomplete snippets without context.
 * @param commands: commands dictionary used for contextual auto-completion
 * @return {function(*=): CompletionResult}: auto complete handling function
 */
function semanticComplete(commands) {
    return (context) => {
        const token_types = ["TimeTag", "Command", "Arg"];

        let base = syntaxTree(context.state).resolve(context.pos, -1);
        let node = matching_node_parent(base, token_types);
        let siblings = sibling_list(node || base, token_types);
        let results = autocomplete(commands, base, siblings, context.state);

        let matching = context.matchBefore(match);
        let extras = {from: ((matching) ? matching.from : context.pos), span: span};

        return (results) ? Object.assign(results, extras) : null;
    };
}

/**
 * Exports the language support object allowing the editing of the F´ sequence language files.
 * @param commands: commands dictionary used for extended language support
 * @return {LanguageSupport} code mirror language support item
 */
export function sequenceLanguageSupport(commands) {
    let semanticCompletion = sequenceLanguage.data.of({
        autocomplete: semanticComplete(commands)
    });
    return new LanguageSupport(sequenceLanguage, [semanticCompletion])
}
