# shimpz-browser

An optional, isolated Browser Service for the
**[Shimpz](https://github.com/roxygens/shimpz)** ecosystem. It keeps a headful
`google-chrome-stable` instance, CDP, XTEST, downloads, and its profile inside one
container. The only control surface is browser-agent's narrow, bearer-token-gated,
audited HTTP API.

The provider-neutral Brain has no Browser network, bearer token, CDP socket,
display, profile, or direct Browser control. A caller outside the model runtime
must explicitly authorize and mediate any Browser capability through the Service
API. Chrome uses a dedicated direct-egress network; no proxy credential or relay
is included.
