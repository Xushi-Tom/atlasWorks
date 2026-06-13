import fs from 'node:fs';
import path from 'node:path';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

function copyCesiumAssets() {
    const sourceDir = path.resolve(__dirname, 'node_modules/cesium/Build/Cesium');
    const targetDir = path.resolve(__dirname, 'dist/cesium');

    return {
        name: 'copy-cesium-assets',
        closeBundle() {
            if (!fs.existsSync(sourceDir)) {
                return;
            }
            fs.rmSync(targetDir, { recursive: true, force: true });
            fs.cpSync(sourceDir, targetDir, { recursive: true });
        }
    };
}

function copyWorldAssets() {
    const sourceDir = path.resolve(__dirname, '../world');
    const targetDir = path.resolve(__dirname, 'dist/world');

    return {
        name: 'copy-world-assets',
        closeBundle() {
            if (!fs.existsSync(sourceDir)) {
                return;
            }
            fs.rmSync(targetDir, { recursive: true, force: true });
            fs.cpSync(sourceDir, targetDir, { recursive: true });
        }
    };
}

function copyBasemapAssets() {
    const sourceDir = path.resolve(__dirname, '../project-assets/basemap/global-imagery-z0-z7');
    const targetDir = path.resolve(__dirname, 'dist/basemap/global-imagery');

    return {
        name: 'copy-basemap-assets',
        closeBundle() {
            if (!fs.existsSync(sourceDir)) {
                return;
            }
            fs.rmSync(targetDir, { recursive: true, force: true });
            fs.cpSync(sourceDir, targetDir, { recursive: true });
        }
    };
}

export default defineConfig({
    base: '/static/',
    plugins: [vue(), copyCesiumAssets(), copyWorldAssets(), copyBasemapAssets()],
    resolve: {
        alias: {
            '@': path.resolve(__dirname, 'src')
        }
    },
    build: {
        outDir: 'dist',
        emptyOutDir: true
    }
});
