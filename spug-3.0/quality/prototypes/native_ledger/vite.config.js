import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { chromium } from "playwright";

let browserPromise;

function getBrowser() {
  if (!browserPromise) {
    browserPromise = chromium.launch({ headless: true });
  }
  return browserPromise;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > 8 * 1024 * 1024) {
        reject(new Error("print payload too large"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function pdfEndpoint() {
  return {
    name: "native-ledger-pdf-endpoint",
    configureServer(server) {
      server.middlewares.use("/api/export-pdf", async (req, res) => {
        if (req.method !== "POST") {
          res.statusCode = 405;
          res.end("POST only");
          return;
        }
        try {
          const body = JSON.parse(await readBody(req));
          if (!body.html || typeof body.html !== "string" || !body.html.includes("<html")) {
            throw new Error("invalid print document");
          }
          const browser = await getBrowser();
          const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
          await page.emulateMedia({ media: "print" });
          await page.setContent(body.html, { waitUntil: "load" });
          await page.evaluate(() => document.fonts.ready);
          const pdf = await page.pdf({
            printBackground: true,
            preferCSSPageSize: true,
            margin: { top: "0", right: "0", bottom: "0", left: "0" },
            displayHeaderFooter: false,
          });
          await page.close();
          const filename = String(body.filename || "native-ledger.pdf").replace(/[^\w.-]+/g, "_");
          res.statusCode = 200;
          res.setHeader("Content-Type", "application/pdf");
          res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
          res.setHeader("Content-Length", pdf.length);
          res.end(pdf);
        } catch (error) {
          res.statusCode = 500;
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          res.end(JSON.stringify({ error: String(error?.message || error) }));
        }
      });
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [react(), pdfEndpoint()],
  server: { port: 4173, strictPort: true, host: "127.0.0.1" },
});
