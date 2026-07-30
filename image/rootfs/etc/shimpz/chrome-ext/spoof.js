// Shimpz stealth — runs in the page MAIN world at document_start (injected by shimpz-glspoof via CDP).
// Hides the server/software tells WITHOUT leaving a detectable toString lie (the classic mistake):
//  - WebGL UNMASKED renderer/vendor → plausible Mesa/Intel (the real backend is SwiftShader; RESEARCH.md §2)
//  - navigator.hardwareConcurrency 96 + deviceMemory 32 → 8/8 (96 cores screams datacenter; deviceMemory>8 is non-spec)
//  - navigator.languages → pt-BR to match the residential SP exit IP
// All overrides report native source via a Function.prototype.toString proxy (defeats lie-detection).
(function () {
  const nativeToString = Function.prototype.toString;
  const fakeSrc = new WeakMap();
  const tsProxy = new Proxy(nativeToString, {
    apply(target, thisArg, args) {
      if (thisArg === tsProxy) return "function toString() { [native code] }";
      if (fakeSrc.has(thisArg)) return fakeSrc.get(thisArg);
      return Reflect.apply(target, thisArg, args);
    },
  });
  try { Function.prototype.toString = tsProxy; } catch (e) {}
  const mask = (fn, name) => { fakeSrc.set(fn, "function " + name + "() { [native code] }"); return fn; };

  // --- WebGL renderer/vendor spoof ---
  const VENDOR = 37445, RENDERER = 37446;
  const spoof = {
    [VENDOR]: "Google Inc. (Intel)",
    [RENDERER]: "ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6 (Core Profile) Mesa 23.2.1)",
  };
  for (const proto of [
    typeof WebGLRenderingContext !== "undefined" && WebGLRenderingContext.prototype,
    typeof WebGL2RenderingContext !== "undefined" && WebGL2RenderingContext.prototype,
  ]) {
    if (!proto) continue;
    const orig = proto.getParameter;
    const patched = mask(function getParameter(p) {
      if (p in spoof) return spoof[p];
      return orig.apply(this, arguments);
    }, "getParameter");
    try { Object.defineProperty(proto, "getParameter", { value: patched, writable: true, configurable: true }); } catch (e) {}
  }

  // --- hardware hints (96 cores / 32 GB → plausible consumer) + locale to match the BR exit IP ---
  const defineGetter = (obj, prop, value, gname) => {
    try {
      const g = mask(function () { return value; }, gname || ("get " + prop));
      Object.defineProperty(obj, prop, { get: g, configurable: true, enumerable: true });
    } catch (e) {}
  };
  defineGetter(Navigator.prototype, "hardwareConcurrency", 8);
  defineGetter(Navigator.prototype, "deviceMemory", 8);
  defineGetter(Navigator.prototype, "languages", ["pt-BR", "pt", "en-US", "en"]);
  // navigator.language (SINGULAR) must agree with languages[0]; a mismatch (real "en-US" vs a pt-BR
  // languages list) is a textbook spoof tell. NOTE: this only fixes the JS surface — the HTTP
  // Accept-Language header is driven by Chrome's own locale, so set --lang=pt-BR too for full consistency.
  defineGetter(Navigator.prototype, "language", "pt-BR");
})();
