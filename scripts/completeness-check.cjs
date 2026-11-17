// Target-owned parsers: typescript, plus @vue/compiler-sfc for Vue sources.
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');

const ignored = new Set(['node_modules', '.git', '.nuxt', 'target', 'dist', 'build',
  '.artifacts', '.venv', '__pycache__', 'coverage']);
const scriptExtensions = new Set(['.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.mts', '.cts', '.vue']);

function scan(root) {
  const files = [];
  function walk(dir) {
    for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
      if (ignored.has(entry.name)) continue;
      const file = path.join(dir, entry.name);
      if (entry.isSymbolicLink()) throw new Error(`Unsupported source symlink: ${file}`);
      if (entry.isDirectory()) walk(file);
      else if (scriptExtensions.has(path.extname(file)) || /\.(java|sql)$/.test(file)) {
        files.push({file, text: fs.readFileSync(file, 'utf8')});
      }
    }
  }
  walk(root);
  let violations = 0;
  const fail = message => { console.log(`[FAIL] ${message}`); violations++; };
  const scripts = files.filter(({file}) => scriptExtensions.has(path.extname(file)) && !file.endsWith('.d.ts'));
  const load = (name, file) => {
    try { return createRequire(file)(name); }
    catch (error) { throw new Error(`Required parser ${name} unavailable for ${file}: ${error.message}`); }
  };
  for (const {file, text} of scripts) {
    const ts = load('typescript', file);
    let blocks = [{content: text, lang: path.extname(file).slice(1), offset: 0}];
    if (file.endsWith('.vue')) {
      const parsed = load('@vue/compiler-sfc', file).parse(text, {filename: file});
      if (parsed.errors.length) throw new Error(`Vue parse error in ${file}: ${parsed.errors.join('; ')}`);
      blocks = [parsed.descriptor.script, parsed.descriptor.scriptSetup].filter(Boolean).map(block => {
        if (block.src) throw new Error(`External Vue script must be checked explicitly: ${file}`);
        if (block.lang && !['js', 'jsx', 'ts', 'tsx'].includes(block.lang)) {
          throw new Error(`Unsupported Vue script language: ${block.lang}`);
        }
        return {...block, offset: block.loc.start.line - 1};
      });
    }
    for (const block of blocks) {
      const kind = {tsx: ts.ScriptKind.TSX, jsx: ts.ScriptKind.JSX, ts: ts.ScriptKind.TS,
        mts: ts.ScriptKind.TS, cts: ts.ScriptKind.TS}[block.lang] || ts.ScriptKind.JS;
      const source = ts.createSourceFile(file, block.content, ts.ScriptTarget.Latest, true, kind);
      if (source.parseDiagnostics.length) {
        throw new Error(`Parse error in ${file}: ${source.parseDiagnostics.map(d => ts.flattenDiagnosticMessageText(d.messageText, ' ')).join('; ')}`);
      }
      function visit(node) {
        if (ts.isFunctionLike(node) && node.body && ts.isBlock(node.body)
            && node.body.statements.every(statement => ts.isEmptyStatement(statement))) {
          // Parameter properties are executable constructor initialization.
          const initialized = ts.isConstructorDeclaration(node) && node.parameters.some(p =>
            (p.modifiers || []).some(m => [ts.SyntaxKind.PublicKeyword, ts.SyntaxKind.PrivateKeyword,
              ts.SyntaxKind.ProtectedKeyword, ts.SyntaxKind.ReadonlyKeyword].includes(m.kind)));
          const callback = node.parent && ts.isCallExpression(node.parent) && node.parent.arguments.includes(node);
          const inner = block.content.slice(node.body.getStart(source) + 1, node.body.end - 1).trim();
          const exception = callback && /^\/\* completeness-allow-empty: [^\r\n]+ \*\/$/.test(inner)
            && !inner.slice(2, -2).includes('*/');
          if (!initialized && !exception) {
            const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1 + block.offset;
            fail(`B-Stub ${path.relative(root, file)}:${line}: empty function body`);
          }
        }
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
  }
  console.log(`[CHECK] Function bodies: ${scripts.length ? scripts.length + ' source files parsed' : 'not applicable (no JS/TS/Vue sources)'}`);
  // Retained legacy heuristics; AST coverage above does not make these semantic checks.
  const frontend = new Set(), backend = new Set(), tables = new Set(), seeded = new Set();
  for (const {file, text} of files) {
    const name = path.relative(root, file);
    if (/TODO|FIXME|HACK|XXX/.test(text)) console.log(`[WARN] Placeholder marker: ${name}`);
    if (/Promise\.resolve|hardcode|demo.*data|mock.*data/.test(text) && /\.(js|vue)$/.test(file)) {
      fail(`Review possible hardcoded/mock data: ${name}`);
    }
    if (/\.(js|vue)$/.test(file)) {
      for (const match of text.matchAll(/request\.(?:get|post|put|delete)\(['"]([^'"]+)['"]/g)) {
        frontend.add(match[1].replace(/^\/api/, '').replace(/^\/v1/, '').replace(/\/[0-9]*$/, ''));
      }
    }
    if (file.endsWith('.java')) {
      for (const match of text.matchAll(/@(?:Get|Post|Put|Delete|Request)Mapping\([^)]*?"([^"]+)"/g)) {
        backend.add(match[1].replace(/^\/api/, '').replace(/^\/v1/, ''));
      }
    }
    if (file.endsWith('.sql')) {
      for (const match of text.matchAll(/CREATE TABLE\s+(?:IF NOT EXISTS\s+)?`?(\w+)`?/g)) tables.add(match[1]);
      for (const match of text.matchAll(/INSERT INTO\s+`?(\w+)`?/g)) seeded.add(match[1]);
    }
  }
  if (frontend.size && backend.size) {
    for (const api of frontend) if (!backend.has(api)) fail(`A-Contract: no extracted backend path for ${api}`);
  } else console.log('[WARN] API text comparison unavailable; use the project contract checker');
  for (const table of tables) if (!seeded.has(table)) console.log(`[WARN] Table without seed data: ${table}`);
  console.log(`[CHECK] Violations: ${violations}`);
  return violations ? 1 : 0;
}

try { process.exitCode = scan(path.resolve(process.argv[2])); }
catch (error) { console.error(`[ERROR] ${error.message}`); process.exitCode = 2; }
