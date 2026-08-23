# Ruck Me Sideways v5

Mobile-first Progressive Web App for rugby analysis.

## Free data connection

The app uses the public `seanyboi/rugbydata` repository through GitHub's public REST API and raw-file endpoints. The companion `rugbypy` project documents match, team, player and competition access. The app never requires a paid API key.

## GitHub Pages

Upload the contents of this folder to the root of your existing `ruck-me-sideways` repository, replacing the old files. Keep `index.html`, `manifest.json`, `sw.js`, and `icon.svg` at the repository root.

Then GitHub Pages will redeploy. Open the same app URL on Android and refresh/reinstall if necessary.

## Notes

- The open data source does not expose every advanced rugby metric. Missing values remain unavailable.
- Do not present calculated or manually entered statistics as provider-sourced facts.
- GitHub Pages cannot run a Node backend; v5 is intentionally browser-only and talks to public GitHub endpoints.
