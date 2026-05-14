/**
 * rendervid_render.js — Rendervid renderer with transparent overlay support
 *
 * Usage:
 *   node rendervid_render.js <template.json> <output.mp4>
 *   node rendervid_render.js <template.json> <output.mov> --transparent
 *
 * --transparent flag outputs ProRes 4444 with alpha channel for FFmpeg compositing.
 */

const fs   = require('fs');
const path = require('path');
const { RendervidEngine }     = require('@rendervid/core');
const { createNodeRenderer }  = require('@rendervid/renderer-node');

async function renderVideo(templatePath, outputPath, transparent = false) {
    console.log('=== Rendervid Renderer ===');
    console.log(`Template:    ${templatePath}`);
    console.log(`Output:      ${outputPath}`);
    console.log(`Transparent: ${transparent}`);

    if (!fs.existsSync(templatePath)) {
        throw new Error(`Template not found: ${templatePath}`);
    }

    const template = JSON.parse(fs.readFileSync(templatePath, 'utf-8'));

    // For transparent rendering, override background to transparent
    if (transparent) {
        if (template.output) {
            template.output.backgroundColor = 'transparent';
        }
        // Strip backgroundColor from each scene too
        if (template.composition && template.composition.scenes) {
            template.composition.scenes.forEach(s => {
                s.backgroundColor = 'transparent';
            });
        }
    }

    const engine     = new RendervidEngine();
    const validation = engine.validateTemplate(template);
    if (!validation.valid) {
        console.error('Template validation failed:');
        console.error(JSON.stringify(validation.errors, null, 2));
        throw new Error('Invalid template');
    }
    console.log('Template valid');

    const renderer = createNodeRenderer({
        verbose:     true,
        concurrency: 4,
    });

    console.log('Rendering...');
    const startTime = Date.now();

    const renderOpts = {
        template:    template,
        outputPath:  outputPath,
        codec:       transparent ? 'prores_ks' : 'libx264',
        quality:     transparent ? 4 : 23,        // ProRes 4444 profile
        pixelFormat: transparent ? 'yuva444p10le' : 'yuv420p',
        concurrency: 4,
    };

    if (transparent) {
        renderOpts.proResProfile = 4;  // 4444 with alpha
    }

    await renderer.renderVideo(renderOpts);

    const duration = ((Date.now() - startTime) / 1000).toFixed(2);
    const stats    = fs.statSync(outputPath);
    console.log(`Render complete in ${duration}s`);
    console.log(`Size: ${(stats.size / 1024 / 1024).toFixed(2)} MB`);

    return { outputPath, size: stats.size };
}

if (require.main === module) {
    const args = process.argv.slice(2);
    if (args.length < 2) {
        console.error('Usage: node rendervid_render.js <template> <output> [--transparent]');
        process.exit(1);
    }

    const templatePath = args[0];
    const outputPath   = args[1];
    const transparent  = args.includes('--transparent');

    renderVideo(templatePath, outputPath, transparent)
        .then(() => process.exit(0))
        .catch(err => {
            console.error('Render failed:', err.message);
            console.error(err.stack);
            process.exit(1);
        });
}

module.exports = { renderVideo };
