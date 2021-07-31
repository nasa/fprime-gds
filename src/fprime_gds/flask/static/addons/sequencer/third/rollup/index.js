import {EditorState, EditorView, basicSetup} from "@codemirror/basic-setup"
import {LanguageSupport, LezerLanguage} from "@codemirror/language"
import {styleTags, tags as t} from "@codemirror/highlight"
import {completeFromList, ifNotIn, snippetCompletion} from "@codemirror/autocomplete"
import {syntaxTree} from "@codemirror/language"
import {linter} from "@codemirror/lint"
import {parser} from "./lang.js"
import "./lang.terms.js"

export {EditorState, EditorView, basicSetup, completeFromList, LanguageSupport, linter, syntaxTree, ifNotIn, snippetCompletion};

let parserWithMetadata = parser.configure({
  props: [
    styleTags({
      TimeTag: t.controlKeyword,
      Command: t.typeName,
      Enum: t.propertyName,
      Integer: t.integer,
      Float: t.float,
      String: t.string,
      LineComment: t.lineComment,
    }),
  ]
});


export const sequenceLanguage = LezerLanguage.define({
  parser: parserWithMetadata,
  languageData: {
    commentTokens: {line: ";"}
  }
});
