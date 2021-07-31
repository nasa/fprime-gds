import {completeFromList, LanguageSupport, syntaxTree, sequenceLanguage, ifNotIn, snippetCompletion} from "./third/code-mirror.es.js";

const match = /[a-zA-Z_0-9$.]+$/;
const span = /\w*$/;


function get_args_template(args, index) {
    let suffix = 0;
    return args.slice(index).map((arg) => arg.type).map(
        (item) => {
            return  "${" + item + "_" + suffix++ +"}";
        }).join(" ");
}


function results(command, index) {
    let args = (command || {args: []}).args;
    let options = [];
    if ((index < args.length) && ("possible" in args[index])) {
        options = args[index].possible.map((item) => {return {label: item}});
    }
    // Add snippet for remaining args
    let template = get_args_template(args, index);
    if (template !== "") {
        options.push(snippetCompletion(template, {label: "$ARGS"}));
    }
    return {options: options};
}

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

// Tokens to look for
let token_types = ["TimeTag", "Command", "Arg"];



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

function matching_node_parent(node, types) {
    let parent = node;
    while (parent != null && types.indexOf(parent.name) === -1) {
        parent = parent.parent;
    }
    return parent;
}

function sibling_list(context, node, types) {
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


function semanticComplete(commands) {
    return (context) => {
        let base = syntaxTree(context.state).resolve(context.pos, -1);
        let node = matching_node_parent(base, token_types);
        let siblings = sibling_list(context, node || base, token_types);
        let results = autocomplete(commands, base, siblings, context.state);

        let matching = context.matchBefore(match);
        let extras = {from: ((matching) ? matching.from : context.pos), span: span};

        return (results) ? Object.assign(results, extras) : null;
    };
}

export function sequenceLanguageSupport(commands) {
    let semanticCompletion = sequenceLanguage.data.of({
        autocomplete: semanticComplete(commands)
    });
    return new LanguageSupport(sequenceLanguage, [semanticCompletion])
}
