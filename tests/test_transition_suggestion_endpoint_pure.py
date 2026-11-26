"""Import-free test for the GET handler's suggestion-only contract.
The full Flask app can't be imported in minimal dev environments without Flask.
"""
import ast
import copy
import unittest
from pathlib import Path
import transitions

class TransitionSuggestionPureTest(unittest.TestCase):
    def test_get_suggests_without_mutating_scenes(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'app.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='documentary_transitions')
        fn.decorator_list=[]
        module=ast.Module(body=[fn],type_ignores=[])
        ast.fix_missing_locations(module)
        source=[{'id':'a','asset_id':'x','in_s':0,'frame_in':0,'frame_out':60,'plan_row':{'source_file':'S01.mp4'}},
                {'id':'b','asset_id':'y','in_s':0,'frame_in':60,'frame_out':120,'plan_row':{'source_file':'S02.mp4'}}]
        before=copy.deepcopy(source)
        rows=[{'scene_index':0,'scene_id':'a','at_s':2.0,'transition':'cut','source':''}]
        class Req:args={'style':'balanced'}
        namespace={'transitions':transitions,'request':Req,'load':lambda pid:{'scenes':source},
                   '_doc_cut_list':lambda p:copy.deepcopy(rows),'jsonify':lambda x:x,
                   '_asset_kinds':lambda p:{}}
        exec(compile(module,'app.py','exec'),namespace)
        result=namespace['documentary_transitions']('fake')
        self.assertEqual(result['suggestion_style'],'balanced')
        self.assertIn('suggested',result['cuts'][0]);self.assertIn('suggested_frames',result['cuts'][0])
        self.assertEqual(source,before,'A GET must not save / change a transition')
        Req.args={'style':'invalid'}
        fallback=namespace['documentary_transitions']('fake')
        self.assertEqual(fallback['suggestion_style'],'balanced')

if __name__=='__main__':unittest.main()
