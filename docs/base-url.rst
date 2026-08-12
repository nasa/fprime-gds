Serving the GDS below a base URL
================================

The HTML GDS can be served below a URL path instead of the web-server root. This is useful when the GDS is placed behind a reverse proxy or when multiple GDS instances share one host.

Use ``--base-url`` when starting the GDS::

   fprime-gds --base-url /mission/gds

The UI and REST resources are then available below ``/mission/gds/``. Omitting ``--base-url`` preserves the existing root-path behavior.

The value must be a URL path, not a complete URL. Schemes, hosts, queries, fragments, empty path segments, and parent-directory segments are rejected.

For example, an nginx location can forward the prefixed path directly to the GDS::

   location /mission/gds/ {
       proxy_pass http://127.0.0.1:5000/mission/gds/;
   }
