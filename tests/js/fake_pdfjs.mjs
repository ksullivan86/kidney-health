// A stand-in for app/static/vendor/pdfjs-dist-6.4.299/pdf.min.mjs, for tests/js/pdf_pages_page.mjs. It has the part of pdf.js 6.4's API that
// js/engine/pdf_pages.js uses, with the behaviour that matters to it: GlobalWorkerOptions.workerPort, getDocument() taking the port and
// posting "configure" to it before it returns (what PDFWorker does in 6.4), a loading task with promise and destroy(), a document with
// numPages and getPage(), a page with getViewport(), render({canvas, viewport, background, annotationMode}), cleanup(), and the exceptions
// by name. `control` is what the test sets and reads; it is the same object in the test and in the page code (one module instance).
export const control = {
  reset() {
    Object.assign(control, {
      mode: 'ok', // ok | password | damaged | hang | noport (pdf.js ignores the port and sets up a fake worker of its own)
      renderMode: 'ok', // ok | fail | hang
      getPageHang: false,
      pages: [[612, 792], [595.28, 841.89]], // points
      events: [], // the order things happened in
      getDocumentCalls: [], // the options object of each getDocument call
      renders: [], // what each render() was given (plus the canvas size at that moment)
    });
  },
};
control.reset();

export class PasswordException extends Error {
  constructor(message, code) { super(message); this.name = 'PasswordException'; this.code = code; }
}
export class InvalidPDFException extends Error {
  constructor(message) { super(message); this.name = 'InvalidPDFException'; }
}
export class RenderingCancelledException extends Error {
  constructor(message) { super(message); this.name = 'RenderingCancelledException'; }
}
export const AnnotationMode = { DISABLE: 0, ENABLE: 1, ENABLE_FORMS: 2, ENABLE_STORAGE: 3 };

export class GlobalWorkerOptions {
  static #port = null;
  static get workerPort() { return this.#port; }
  static set workerPort(value) {
    control.events.push(value === null ? 'workerPort=null' : 'workerPort=set');
    this.#port = value;
  }
}

function makePage(number) {
  const [width, height] = control.pages[number - 1];
  return {
    getViewport: ({ scale }) => ({ width: width * scale, height: height * scale, scale }),
    render(params) {
      control.renders.push({ ...params, canvasWidth: params.canvas.width, canvasHeight: params.canvas.height, page: number });
      let settle;
      const promise = new Promise((resolve, reject) => { settle = { resolve, reject }; });
      if (control.renderMode === 'ok') settle.resolve();
      else if (control.renderMode === 'fail') settle.reject(new Error('bad content stream'));
      return {
        promise,
        cancel() { control.events.push('render.cancel'); settle.reject(new RenderingCancelledException('Rendering cancelled')); },
      };
    },
    cleanup() { control.events.push(`cleanup:${number}`); },
  };
}

export function getDocument(params) {
  control.events.push('getDocument');
  control.getDocumentCalls.push(params);
  const port = GlobalWorkerOptions.workerPort;
  if (control.mode !== 'noport' && port) port.postMessage({ action: 'configure' }); // PDFWorker.create({port}) does this synchronously
  const task = {
    onPassword: null,
    destroyed: false,
    async destroy() { task.destroyed = true; control.events.push('task.destroy'); },
  };
  task.promise = new Promise((resolve, reject) => {
    if (control.mode === 'hang') return;
    if (control.mode === 'password') { reject(new PasswordException('No password given', 1)); return; }
    if (control.mode === 'damaged') { reject(new InvalidPDFException('Invalid PDF structure.')); return; }
    resolve({
      numPages: control.pages.length,
      getPage: (n) => (control.getPageHang ? new Promise(() => {}) : Promise.resolve(makePage(n))),
    });
  });
  return task;
}
