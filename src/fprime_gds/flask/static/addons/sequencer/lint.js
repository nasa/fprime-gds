/**
 * Linting support code for integration with the editor.
 */

const LINE_END = /\r?\n/;
const LINE_REG = /Line\s*(\d+):/;
const LINT_SRC = "F´ Sequence Checker";

/**
 * Given a line of the response from the linter (sequence generator), respond with a editor-localized error diagnostic
 * such that the code will be underlined upon error.
 * @param view: editor view to use for locating line numbers
 * @param line: line to process
 * @return Diagnostic type to be sent to code editor
 */
function buildDiagnostic(view, line) {
    let diagnostic = {severity: "error", message: line, source: LINT_SRC, from:0, to:0};
    let match = line.match(LINE_REG);
    if (match != null) {
        let line_number = parseInt(match[1]);
        let line = view.state.doc.line(line_number);
        Object.assign(diagnostic, {from: line.from, to:line.to});
    }
    return diagnostic;
}

/**
 * Process a given message (string or object with .error sub property) into a set of diagnostics, one per non-empty line
 * in the error/message.
 * @param view: editor view to pass into the diagnostic builder
 * @param message: message to process (from server)
 * @return Diagnostic[] passed to editor's linter
 */
export function processResponse(view, message) {
    let errors = message.error || ""; // Only process errors
    let lines = errors.split(LINE_END).map((line) => line.trim()).filter((line) => line !== "");
    return lines.map((line) => buildDiagnostic(view, line));
}
