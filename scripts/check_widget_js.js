/* Синтаксическая проверка инлайн-скриптов виджета: node scripts/check_widget_js.js widgets/<name>/index.html
 * Виджеты — самостоятельные HTML-файлы без сборки, поэтому опечатка в <script>
 * ловится только в браузере OBS. Этот скрипт ловит её на месте. */
const fs = require('fs');

const target = process.argv[2];
if (!target) {
  console.error('usage: node scripts/check_widget_js.js <widget-html>');
  process.exit(2);
}
const html = fs.readFileSync(target, 'utf8');
const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
if (!blocks.length) {
  console.error(`${target}: no inline <script> blocks found`);
  process.exit(1);
}
blocks.forEach((body, i) => {
  try {
    new Function(body);
  } catch (e) {
    console.error(`${target}: block ${i} syntax error: ${e.message}`);
    process.exit(1);
  }
});
console.log(`${target}: ${blocks.length} script block(s) OK`);
