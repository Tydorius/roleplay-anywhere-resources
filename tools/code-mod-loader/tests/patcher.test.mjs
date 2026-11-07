// node --test   (from tools/code-mod-loader)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { parseArgs, libraryPaths, gameVersion, bundledMods, resolveMods, defaultModsDir } from '../patch.mjs';

test('parseArgs takes a command, mod names and --game', () => {
  assert.deepEqual(parseArgs([]), { cmd: 'status', game: null, names: [] });
  assert.deepEqual(parseArgs(['add', 'portals', '--game', 'E:\\Games\\Anywhere RPG', 'floors']),
    { cmd: 'add', game: 'E:\\Games\\Anywhere RPG', names: ['portals', 'floors'] });
  assert.throws(() => parseArgs(['install', '--gmae', 'x']), /unknown argument: --gmae/);
});

test('libraryPaths reads every library from libraryfolders.vdf', () => {
  const vdf = `"libraryfolders"
{
	"0"
	{
		"path"		"C:\\\\Program Files (x86)\\\\Steam"
		"apps"
		{
			"228980"		"672897464"
		}
	}
	"1"
	{
		"path"		"D:\\\\SteamLibrary"
	}
	"2"
	{
		"path"		"/home/me/.local/share/Steam"
	}
}`;
  assert.deepEqual(libraryPaths(vdf), ['C:\\Program Files (x86)\\Steam', 'D:\\SteamLibrary', '/home/me/.local/share/Steam']);
});

test('gameVersion finds the version constant beside the log levels', () => {
  assert.equal(gameVersion('const WI=!1,Z9=!0,KI="0.18",Bg={},KC={error:0,warn:1,info:2};'), '0.18');
  assert.equal(gameVersion('a$="1.2.3",b={},c={error:0,warn:1}'), '1.2.3');
  assert.equal(gameVersion('KI="0.18",Bg={x:1},KC={error:0,warn:1}'), null);
});

test('add with no names (or "all") takes every bundled mod but the samples', () => {
  const avail = bundledMods();
  assert.ok(avail.includes('portals') && avail.includes('memory-add'));
  const all = resolveMods([], avail);
  assert.ok(!all.includes('memory-add'));
  assert.equal(all.length, avail.length - 1);
  assert.deepEqual(resolveMods(['all'], avail), all);
  assert.deepEqual(resolveMods(['all', 'memory-add'], avail), [...all, 'memory-add']);
  assert.deepEqual(resolveMods(['floors', 'portals', 'floors'], avail), ['floors', 'portals']);
  assert.throws(() => resolveMods(['portal'], avail), /no bundled mod named "portal"/);
});

test('the code-mods folder follows each system\'s conventions', () => {
  assert.equal(defaultModsDir('win32', { APPDATA: 'C:\\Users\\me\\AppData\\Roaming' }, 'C:\\Users\\me'),
    path.join('C:\\Users\\me\\AppData\\Roaming', 'Anywhere RPG', 'code-mods'));
  assert.equal(defaultModsDir('darwin', {}, '/Users/me'),
    path.join('/Users/me', 'Library', 'Application Support', 'Anywhere RPG', 'code-mods'));
  assert.equal(defaultModsDir('linux', {}, '/home/me'), path.join('/home/me', '.config', 'Anywhere RPG', 'code-mods'));
  assert.equal(defaultModsDir('linux', { XDG_CONFIG_HOME: '/cfg' }, '/home/me'), path.join('/cfg', 'Anywhere RPG', 'code-mods'));
});
