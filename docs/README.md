# Integration docs

Run these commands from `docs/` with Node 24.22.3 and npm 11.19.1. Use `npm ci` to install the versions in `package-lock.json`.

```sh
npm ci
npm run dev
```

Open the local address printed by Astro. To build the static HTML in `dist/`, run `npm run build`. To test the build under a repository path instead of `/`, use the same base for both commands:

```sh
DOCS_BASE=/cedarpy-integrations/ npm run build
DOCS_BASE=/cedarpy-integrations/ npm run preview
```

Open `/cedarpy-integrations/` on the preview server and follow a guide link. If Astro starts a server in the background, stop it with `npm run preview -- stop` or `npm run dev -- stop`.

## Guide files

Write plain Markdown in `src/content/docs/guides/`. Start each file with a `title` in YAML frontmatter. The filename sets the path. For example, `fastapi.md` appears at `guides/fastapi/`. The navigation is defined in `src/guides.ts`. Keep the SQLAlchemy guide with the framework guides, but identify it as source only. Use relative links such as `../flask/` between guides. For source examples, use a fenced code block with a language name and link to the upstream release or commit.

Use `cedar` fences for policies and `cedarschema` for schemas. Existing `cedar` fences that start with a schema declaration also work. Shiki uses local copies of the [official Cedar grammars](https://github.com/cedar-policy/vscode-cedar/tree/eb63daec70f2ee8b14b049707cc787678918901b/syntaxes). To update them, copy both grammar files from the same commit into `grammars/vscode-cedar/`, copy its `LICENSE` and `NOTICE`, and update the link here.

The three `cedarpy-*.md` reference pages contain the upstream guides from `k9securityio/cedar-py` v4.12.2 (`f9a3af1fe49b8ffe6a3764da9ed19bf832227ade`). They ship in that release’s source archive under `docs/guides/`, not alongside the installed Python module. The website keeps its own copy so a build needs neither a Cedar checkout nor a GitHub fetch. When updating, compare against the new release and retain the source credit, `public/licenses/cedar-py-4.12.2.txt` (update the filename with the version), and any clearly marked corrections.

## Publish to GitHub Pages

Check the intended audience first. A private repository does not guarantee a private Pages site, and private-repository Pages support depends on your GitHub plan. When ready, select **Settings → Pages → Source → GitHub Actions**. After the workflow is on the default branch, choose **Actions → Publish docs to GitHub Pages → Run workflow** on that branch. It reads the site's base path, builds Astro, and deploys only `docs/dist/`. Pushes do not publish the site.
