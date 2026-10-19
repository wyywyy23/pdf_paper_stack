"""Regression tests for real option, file-preservation and failure boundaries."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import paper_stack as ps
import run_pipeline as pipeline


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.addCleanup(patch.stopall)
        patch.object(ps, 'ROOT', self.root).start()
        self.config = {'default_paper': 'sample', 'papers': {'sample': {
            'pdf': 'paper.pdf', 'images': 'pages', 'blend': 'prj/sample.blend'}},
            'preprocess': {'dpi': 72, 'image_format': 'JPEG', 'extension': 'jpg'},
            'random': {'stack_seed': 1, 'asset_seed': 2, 'seeds': [10, 20]},
            'scene': {'render': {'samples': 1024, 'denoise': False, 'resolution': [1920, 1080]},
                      'camera': {'lens': 85}}}
        (self.root / 'config').mkdir()
        (self.root / 'paper.pdf').write_bytes(b'original-pdf')
        (self.root / 'config/assets.yml').write_text('assets: {}\n')
        self.save_config()

    def save_config(self):
        (self.root / 'config/pipeline.yml').write_text(yaml.safe_dump(self.config))

    def images(self, count):
        return [Image.new('RGB', (8, 12), (n, 30, 40)) for n in range(count)]

    def test_defaults_follow_selected_config(self):
        o = pipeline.options({})
        self.assertEqual(o.paper, 'sample')
        self.assertFalse(o.auto_variant)
        self.assertFalse(o.random_variant)
        self.assertEqual((o.samples, o.denoise), (1024, False))
        self.assertEqual(pipeline.options({'PAPER': 'sample'}).paper, o.paper)
        alternate = copy.deepcopy(self.config)
        alternate['papers']['alternate'] = alternate['papers']['sample']
        alternate['default_paper'] = 'alternate'
        (self.root / 'alternate.yml').write_text(yaml.safe_dump(alternate))
        self.assertEqual(pipeline.options({'PIPELINE': 'alternate.yml'}).paper, 'alternate')

    def test_stack_layout_options_and_separate_paths(self):
        fan = pipeline.options({})
        stack = pipeline.options({'LAYOUT': 'stack'})
        self.assertEqual(fan.layout, 'fan')
        self.assertEqual(stack.layout, 'stack')
        self.assertNotEqual(fan.output_blend, stack.output_blend)
        self.assertNotEqual(fan.output, stack.output)
        self.assertNotEqual(fan.render_output, stack.render_output)
        self.assertTrue(stack.output_blend.endswith('sample_stack.blend'))
        variant = pipeline.options({'LAYOUT': 'stack', 'VARIANT': 'hero'})
        self.assertTrue(variant.output_blend.endswith('sample_stack_vhero.blend'))
        self.assertTrue(pipeline.options({'LAYOUT': 'stack', 'RANDOM_VARIANT': '1'}).output_blend.endswith('sample_stack_random.blend'))
        with self.assertRaises(ValueError): pipeline.options({'LAYOUT': 'wrong'})
        for bad in ['0', '-0.1', 'nan', 'inf']:
            with self.subTest(thickness=bad), self.assertRaises(ValueError):
                pipeline.options({'LAYOUT': 'stack', 'STACK_PAGE_THICKNESS': bad})
        with self.assertRaises(ValueError): pipeline.options({'LAYOUT': 'stack', 'STACK_PAGE_GAP': '-1'})
        with self.assertRaises(ValueError): pipeline.options({'STACK_PAGE_THICKNESS': '.001'})

    def test_stack_settings_reach_json_and_config_defaults(self):
        o = pipeline.options({'LAYOUT': 'stack', 'STACK_PAGE_THICKNESS': '.002', 'STACK_PAGE_GAP': '0'})
        pipeline.scene_json(o)
        settings = json.loads(Path(o.output).read_text())['scene']['stack']
        self.assertEqual(settings['layout'], 'stack')
        self.assertEqual(settings['compact']['page_thickness'], .002)
        self.assertEqual(settings['compact']['page_gap'], 0)
        self.config['scene']['stack'] = {'layout': 'stack'}
        self.save_config()
        self.assertEqual(pipeline.options({}).layout, 'stack')
        ps.main(['scene-json'])
        self.assertTrue((self.root/'build/sample_stack.scene.json').is_file())

    def test_boolean_flags_and_conflicts(self):
        for value in ['0', 'false', 'off', 'no']:
            self.assertFalse(pipeline.options({'RANDOM_VARIANT': value}).random_variant)
        self.assertTrue(pipeline.options({'RANDOM_VARIANT': '1'}).random_variant)
        with self.assertRaises(ValueError): pipeline.options({'RANDOM_VARIANT': 'maybe'})
        with self.assertRaises(ValueError): pipeline.options({'VARIANT': '1', 'RANDOM_VARIANT': '1'})
        self.assertEqual(pipeline.options({'VARIANT': '1', 'RANDOM_VARIANT': '0'}).variant, '1')
        with self.assertRaises(ValueError): pipeline.options({'PAPER_ID': 'sample', 'PAPER': 'other'})

    def test_rejects_invalid_inputs_before_writing(self):
        for env in [{'DPI': '0'}, {'SAMPLES': '-1'}, {'RESOLUTION': '0x400'},
                    {'RENDER_FRAME': 'bad'}, {'VARIANT': '../escape'}, {'VARIANT': '0'}]:
            with self.subTest(env=env), self.assertRaises(ValueError): pipeline.options(env)
        self.assertFalse((self.root / 'build').exists())

    def test_pdf_images_and_quality_reach_scene_json(self):
        o = pipeline.options({'PDF': 'other.pdf', 'IMAGE_DIR': 'custom pages',
                              'SAMPLES': '16', 'RESOLUTION': '320x180', 'DENOISE': '1'})
        pipeline.scene_json(o)
        data = json.loads(Path(o.output).read_text())
        self.assertEqual(data['paper']['pdf'], str(self.root / 'other.pdf'))
        self.assertEqual(data['paper']['images'], str(self.root / 'custom pages'))
        self.assertEqual(data['scene']['render'], {'samples': 16, 'resolution': [320, 180], 'denoise': True})

    def test_config_arguments_and_relocation_cannot_reuse_stale_json(self):
        o = pipeline.options({})
        pipeline.scene_json(o)
        data = json.loads(Path(o.output).read_text())
        data['project_root'] = '/old/machine'
        Path(o.output).write_text(json.dumps(data))
        self.config['scene']['camera']['lens'] = 100
        self.save_config()
        pipeline.scene_json(pipeline.options({'IMAGE_DIR': 'new pages'}))
        data = json.loads(Path(o.output).read_text())
        self.assertEqual(data['project_root'], str(self.root))
        self.assertEqual(data['paper']['images'], str(self.root / 'new pages'))
        self.assertEqual(data['scene']['camera']['lens'], 100)
        self.assertTrue(list((Path(o.output).parent / 'history').glob('*.json')))

    def test_random_render_reuses_seeds_but_explicit_build_draws_new(self):
        o = pipeline.options({'RANDOM_VARIANT': '1'})
        with patch.object(ps.secrets, 'randbelow', side_effect=[0, 1, 1, 0, 1, 1]):
            pipeline.scene_json(o)
            first = json.loads(Path(o.output).read_text())
            pipeline.scene_json(o, reuse_random=True)
            second = json.loads(Path(o.output).read_text())
            self.assertEqual(first['random'], second['random'])
            pipeline.scene_json(o)
            third = json.loads(Path(o.output).read_text())
            self.assertNotEqual(first['random'], third['random'])

    def test_preprocess_removes_stale_pages_and_keeps_unrelated_files(self):
        o = pipeline.options({})
        with patch.object(ps, 'convert_from_path', return_value=self.images(2)):
            pipeline.preprocess(o)
        (Path(o.images) / 'notes.txt').write_text('keep')
        (Path(o.images) / 'cover.png').write_bytes(b'keep-unrelated')
        with patch.object(ps, 'convert_from_path', return_value=self.images(1)):
            pipeline.preprocess(o, force=True)
        self.assertFalse((Path(o.images) / 'page_1.jpg').exists())
        self.assertEqual((Path(o.images) / 'notes.txt').read_text(), 'keep')
        self.assertEqual((Path(o.images) / 'cover.png').read_bytes(), b'keep-unrelated')
        self.assertTrue(list((Path(o.images) / 'history').glob('*/page_1.jpg')))

    def test_preprocess_cache_checks_pdf_and_page_bytes(self):
        o = pipeline.options({})
        with patch.object(ps, 'convert_from_path', side_effect=lambda *a, **kw: self.images(1)) as convert:
            pipeline.preprocess(o)
            pipeline.preprocess(o)
            self.assertEqual(convert.call_count, 1)
            (Path(o.images) / 'page_0.jpg').write_bytes(b'changed')
            pipeline.preprocess(o)
            self.assertEqual(convert.call_count, 2)
            (self.root / 'paper.pdf').write_bytes(b'new pdf')
            pipeline.preprocess(o)
            self.assertEqual(convert.call_count, 3)

    def test_failed_conversion_preserves_existing_pages(self):
        o = pipeline.options({})
        with patch.object(ps, 'convert_from_path', return_value=self.images(1)):
            pipeline.preprocess(o)
        old = (Path(o.images) / 'page_0.jpg').read_bytes()
        with patch.object(ps, 'convert_from_path', side_effect=RuntimeError('conversion failed')):
            with self.assertRaises(RuntimeError): pipeline.preprocess(o, force=True)
        self.assertEqual((Path(o.images) / 'page_0.jpg').read_bytes(), old)

    def test_blender_build_failure_and_empty_success_preserve_scene(self):
        o = pipeline.options({})
        output = Path(o.output_blend)
        output.parent.mkdir()
        output.write_bytes(b'original scene')
        with patch.object(pipeline, 'preprocess'), patch.object(pipeline, 'run', side_effect=subprocess.CalledProcessError(2, ['blender'])):
            with self.assertRaises(subprocess.CalledProcessError): pipeline.build(o)
        self.assertEqual(output.read_bytes(), b'original scene')
        with patch.object(pipeline, 'preprocess'), patch.object(pipeline, 'run'):
            with self.assertRaises(RuntimeError): pipeline.build(o)
        self.assertEqual(output.read_bytes(), b'original scene')

    def test_blender_build_success_archives_previous_scene(self):
        o = pipeline.options({})
        output = Path(o.output_blend); output.parent.mkdir(); output.write_bytes(b'original')
        def fake(command):
            self.assertIn('--python-exit-code', command)
            Path(command[command.index('--output') + 1]).write_bytes(b'new scene')
        with patch.object(pipeline, 'preprocess'), patch.object(pipeline, 'run', side_effect=fake):
            pipeline.build(o)
        self.assertEqual(output.read_bytes(), b'new scene')
        self.assertEqual(next((output.parent / 'history').glob('*.blend')).read_bytes(), b'original')

    def test_failed_render_does_not_replace_old_image_or_claim_success(self):
        o = pipeline.options({'BLEND': 'saved.blend'})
        Path(o.output_blend).write_bytes(b'scene')
        final = Path(o.render_output.replace('####', '0001') + '.png')
        final.parent.mkdir(parents=True); Image.new('RGB', (3, 3)).save(final)
        previous = final.read_bytes(); out = io.StringIO()
        with patch.object(pipeline, 'run', side_effect=subprocess.CalledProcessError(2, ['blender'])), contextlib.redirect_stdout(out):
            with self.assertRaises(subprocess.CalledProcessError): pipeline.render(o)
        self.assertEqual(final.read_bytes(), previous)
        self.assertNotIn('Rendered successfully', out.getvalue())
        with patch.object(pipeline, 'run'):
            with self.assertRaises(RuntimeError): pipeline.render(o)
        self.assertEqual(final.read_bytes(), previous)

    def test_render_verifies_new_png_and_archives_previous_output(self):
        o = pipeline.options({'BLEND': 'saved.blend', 'SAMPLES': '4'})
        Path(o.output_blend).write_bytes(b'scene')
        final = Path(o.render_output.replace('####', '0001') + '.png')
        final.parent.mkdir(parents=True); Image.new('RGB', (3, 3)).save(final)
        def fake(command):
            expression = command[command.index('--python-expr') + 1]
            self.assertIn('samples=4', expression)
            self.assertNotIn('resolution_x', expression)
            output = str(command[command.index('--render-output') + 1]).replace('####', '0001') + '.png'
            Image.new('RGB', (8, 12)).save(output)
        with patch.object(pipeline, 'run', side_effect=fake): pipeline.render(o)
        with Image.open(final) as image: self.assertEqual(image.size, (8, 12))
        self.assertEqual(len(list((final.parent / 'history').glob('*.png'))), 1)

    def test_make_and_direct_entry_resolve_the_same_default_and_spaces(self):
        shutil.copytree(SCRIPTS, self.root / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(SCRIPTS.parent / 'Makefile', self.root / 'Makefile')
        env = {k: v for k, v in os.environ.items() if k not in ['PAPER', 'PAPER_ID', 'PIPELINE', 'VARIANT', 'RANDOM_VARIANT', 'IMAGE_DIR', 'PDF', 'BLEND', 'SCENE_JSON', 'SAMPLES', 'RESOLUTION', 'DENOISE', 'LAYOUT', 'STACK_PAGE_THICKNESS', 'STACK_PAGE_GAP']}
        subprocess.run(['make', 'scene-json', 'PYTHON=' + sys.executable, 'IMAGE_DIR=pages with spaces'], cwd=self.root, env=env, check=True, capture_output=True)
        data = json.loads((self.root / 'build/sample.scene.json').read_text())
        self.assertEqual(data['paper_id'], 'sample')
        self.assertEqual(data['paper']['images'], str(self.root / 'pages with spaces'))


class CompactStyleValidationTests(unittest.TestCase):
    def test_surface_defaults_match_calibrated_three_dimensional_field(self):
        compact = ps.stack_settings({}, layout="stack")["compact"]
        self.assertEqual((compact["paper_surface_strength"], compact["paper_surface_distance"], compact["paper_surface_seed"]), (0.5, 0.5, 0.0))

    def test_style_rejects_bad_focus_outliers_and_lights(self):
        for compact in ({"focus_uv": [0.5, 2]}, {"outlier_fraction": 1.1}, {"edge_curl": -1}, {"paper_surface_strength": -1}, {"paper_surface_falloff": 0}, {"paper_surface_distance": float("nan")}, {"lighting": {"energy": -1}}, {"lighting": {"spot_size_degrees": 0}}):
            with self.assertRaises(ValueError):
                ps.stack_settings({"compact": compact}, layout="stack")


if __name__ == '__main__': unittest.main()
