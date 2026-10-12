// Node's type stripper does not resolve the extensionless imports used by Rollup.
// Limit that fallback to this plugin's own TypeScript source modules.
const sourceRoot = new URL('../src/', import.meta.url).href;
export async function resolve(specifier, context, nextResolve) {
  try { return await nextResolve(specifier, context); }
  catch (error) {
    if (error.code !== 'ERR_MODULE_NOT_FOUND' || !context.parentURL?.startsWith(sourceRoot) ||
        !/^\.\/[A-Za-z]+$/.test(specifier)) throw error;
    return nextResolve(specifier + '.ts', context);
  }
}
