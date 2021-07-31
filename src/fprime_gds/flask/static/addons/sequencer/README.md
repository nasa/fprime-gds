# Sequencer Plugin

Sets up a sequence builder Vue.js component used to build sequences and submit them to the GDS using the `/sequence`
rest endpoint. 

## Attributions

This code makes use of Code Mirror 6 and Lezer. Attributions are placed here due to the JavaScript bundling process
obscuring the in code headers.

**Codemirror 6**:

Copyright (C) 2018 by Marijn Haverbeke <marijnh@gmail.com>, Adrian Heine <mail@adrianheine.de>, and others 

**Lezer**:

Copyright (C) 2018 by Marijn Haverbeke <marijnh@gmail.com> and others

## Bundling Libraries

Modern JavaScript bundles libraries, HTML, CSS, and application code into a single bundle that is included in the
primary application. The `fprime-gds` is not designed to be bundled in this way. Thus to make use of the modern
libraries, they need to be built and then included in the addon as a single unit. This code is pre-built but may be
rebuilt using: NPM, and Rollup.js.

**Note:** webpack does not seem to allow bundling of libraries with the intent to include them elsewhere.

#### Install Node Dependencies and Rebuild Code Mirror Bundle

```bash
cd .../third/rollup
npm i
npm run build
```

## When to Rebuild the Bundle

Some changes require a rebuild of the bundle.  These include code highlighting definitions and the F´ sequence
language's grammar.

**Code Highlighting:** token to highlighting definitions are set in `.../third/rollup/index.js` and provided as part of
the exported sequence language support.

**Language Definitions:** The Lezer language definition for the F´ sequence language is set in
`.../third/rollup/laguage.grammer`.  The language support files are built as part of the bundling process.