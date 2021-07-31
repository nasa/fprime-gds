import pkg from './package.json';
import { nodeResolve } from '@rollup/plugin-node-resolve';


export default [
    {
        input: 'index.js',
        output: [
            { file: pkg.module, format: 'es' }
        ],
        plugins: [nodeResolve()]
    }
];
