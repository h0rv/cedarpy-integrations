import { defineConfig } from 'astro/config';
import cedar from './grammars/vscode-cedar/cedar.tmLanguage.json' with { type: 'json' };
import cedarSchema from './grammars/vscode-cedar/cedarschema.tmLanguage.json' with { type: 'json' };

export default defineConfig({
  base: process.env.DOCS_BASE || '/',
  trailingSlash: 'always',
  markdown: {
    shikiConfig: {
      themes: { light: 'github-light', dark: 'github-dark' },
      langs: [{ ...cedar, name: 'cedar' }, { ...cedarSchema, name: 'cedarschema' }],
      transformers: [{
        preprocess(code, options) {
          if (options.lang !== 'cedar') return;
          // Older guides use `cedar` for both policies and schema declarations.
          const declaration = code.match(/^\s*(permit|forbid|namespace|entity|type|action)\b/m)?.[1];
          if (declaration && declaration !== 'permit' && declaration !== 'forbid') {
            options.lang = 'cedarschema';
          }
        },
      }],
    },
  },
  devToolbar: { enabled: false },
});
