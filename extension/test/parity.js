// Runs the JS detector on dumped frames and prints its verdict.
const fs = require('fs');
const { FlashDetector, toSegments } = require('../detector.js');
const buf = fs.readFileSync(process.argv[2]);
const w = buf.readUInt32LE(0), h = buf.readUInt32LE(4), n = buf.readUInt32LE(8), fps = buf.readFloatLE(12);
const det = new FlashDetector(w, h);
const size = w * h * 4;
const samples = [];
for (let i = 0; i < n; i++) {
  const rgba = new Uint8ClampedArray(buf.buffer, buf.byteOffset + 16 + i * size, size);
  samples.push(det.push(rgba, i / fps));
}
const worst = Math.max(...samples.map((s) => s.worst));
const segs = toSegments(samples);
const verdict = segs.length ? 'FAIL' : worst >= 5 ? 'CAUTION' : 'PASS';
console.log(JSON.stringify({ verdict, peak: worst / 2, red: segs.some((s) => s.red), segments: segs.map((s) => [s.start.toFixed(2), s.end.toFixed(2)]) }));
