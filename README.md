# Ruck Me Sideways v6

Proper mobile Match Search/Import Engine using the public `seanyboi/rugbydata` v3 Parquet database. It loads team and competition registries first, then reads the selected team's match file and finally the individual match file. The app runs from GitHub Pages with no paid API key.

Browser Parquet reader: hyparquet via jsDelivr, using HTTP range requests.

To update GitHub Pages, replace the existing app files with the contents of this folder and keep `index.html` at repository root.
