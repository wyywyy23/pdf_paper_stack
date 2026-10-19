"""Run with blender --background --factory-startup --python-exit-code 1 --python ..."""
import bpy
import json
import math
from pathlib import Path
import random
import sys
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import blender_build_scene as build


def fake_page(path):
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0,0,0))
    obj=bpy.context.object
    obj.name=path.stem
    for vertex in obj.data.vertices: vertex.co.x *= .707
    material=bpy.data.materials.new('Printed page')
    obj.data.materials.append(material)
    return obj


class ZeroRng:
    def gauss(self, mu, sigma): return 0.0


def reset(n):
    build.clear_scene()
    build.page_images=lambda _: [Path(f'page_{i}.jpg') for i in range(n)]
    build.import_page_plane=fake_page
    build.configure_page_material=lambda *args: None
    bpy.context.scene.cursor.location=(0,0,0)
    bpy.context.scene.tool_settings.transform_pivot_point='MEDIAN_POINT'


def signature():
    bpy.context.view_layer.update()
    return [(obj['paper_index'],tuple(round(v,8) for v in obj.location),round(obj.rotation_euler.z,8))
            for obj in sorted(bpy.context.scene.objects,key=lambda obj:obj['paper_index'])]


# Preserve the original short-paper opening and minimum step on longer papers.
for count, step in [(3,4.0),(11,1.5),(56,1.5)]:
    reset(count)
    bottom=build.build_stack(Path('/unused'),{'layout':'fan','rotation_sign':-1},ZeroRng())
    bpy.context.view_layer.update()
    objects={int(obj.name.split('_')[1]):obj for obj in bpy.context.scene.objects}
    for index,obj in objects.items():
        assert math.isclose(math.degrees(obj.rotation_euler.z),step*index,abs_tol=1e-4)
        assert abs(obj.location.x)+abs(obj.location.y)+abs(obj.location.z)<1e-7
    assert math.isclose(bottom,-count*.0005,abs_tol=1e-7)

# Real solid geometry, a bounded footprint, positive paper gaps and deterministic layout.
reset(56)
# Stack mode must be independent of a user's current cursor and transform pivot.
bpy.context.scene.cursor.location=(10,20,30)
bpy.context.scene.tool_settings.transform_pivot_point='CURSOR'
bottom=build.build_stack(Path('/unused'),{'layout':'stack','compact':{'outlier_fraction':0,'edge_curl':0}},random.Random(2211024416))
bpy.context.view_layer.update()
first=signature()
objects=sorted(bpy.context.scene.objects,key=lambda obj:obj['paper_index'])
assert len(objects)==56
bounds=[]
for obj in objects:
    evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    points=[evaluated.matrix_world@Vector(corner) for corner in evaluated.bound_box]
    low,high=min(p.z for p in points),max(p.z for p in points)
    assert math.isclose(high-low,.0012,abs_tol=1e-6)
    assert abs(obj.location.x)<=.0015+1e-7
    assert abs(obj.location.y-2.0)<=.0015+1e-7
    assert abs(math.degrees(obj.rotation_euler.z))<=.25+1e-6
    bounds.append((low,high))
for index in range(1,len(bounds)):
    assert math.isclose(bounds[index-1][0]-bounds[index][1],.00008,abs_tol=1e-6)
assert math.isclose(bottom,-.0716,abs_tol=1e-6)
assert math.isclose(bounds[0][1]-bounds[-1][0],.0716,abs_tol=1e-6)
assert objects[0].rotation_euler.z==0 and objects[0].location.x==0
reset(56)
build.build_stack(Path('/unused'),{'layout':'stack','compact':{'outlier_fraction':0,'edge_curl':0}},random.Random(2211024416))
assert first==signature()
# The actual saved camera must show all corners of the solid pile, not crop its front edge.
from bpy_extras.object_utils import world_to_camera_view
build.configure_render({'resolution':[960,540]})
camera=build.add_camera({'rotation_degrees':[45,0,-10],'lens':85,'dof':{'enabled':True,'fstop':1.8}})
original_azimuth=camera.rotation_euler.z
build.frame_compact_stack(camera,{'layout':'stack','compact':{'outlier_fraction':0,'edge_curl':0}})
assert camera.rotation_euler.z==original_azimuth
assert math.isclose(math.degrees(camera.rotation_euler.x),55.0,abs_tol=1e-5)
assert camera.data.dof.aperture_fstop==4.0
for obj in [obj for obj in bpy.context.scene.objects if obj.get('paper_stack_layout')=='stack']:
    evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    for corner in evaluated.bound_box:
        point=world_to_camera_view(bpy.context.scene,camera,evaluated.matrix_world@Vector(corner))
        assert .01<point.x<.99 and .01<point.y<.99 and point.z>0, tuple(point)
# Fewer pages physically give a thinner stack under the same styling.
reset(11)
short=build.build_stack(Path('/unused'),{'layout':'stack','compact':{'outlier_fraction':0,'edge_curl':0}},ZeroRng())
assert abs(short)<abs(bottom)
# A table-level prop inside the pile must be shifted clear rather than buried.
bpy.ops.mesh.primitive_cube_add(size=.1,location=(.1,2,-.005))
prop=bpy.context.object
collection=bpy.data.collections.new('Loose prop collection')
bpy.context.scene.collection.children.link(collection)
collection.objects.link(prop)
build.place_stack_table_props({'layout':'stack','compact':{'outlier_fraction':0,'edge_curl':0}},
    {'prop':{'kind':'collection','root_object':prop.name,'transform':{'z_reference':'table'}}},
    {'prop':collection})
bpy.context.view_layer.update()
assert min((prop.matrix_world@Vector(c)).x for c in prop.bound_box)>.35
print('LAYOUT_CHECK:'+json.dumps({'fan_page_counts':[3,11,56],'fan_steps':[4,1.5,1.5],
 'stack_pages':56,'page_thickness':.0012,'gap':.00008,'depth':abs(bottom),
 'short_11_page_depth':abs(short),'same_seed_reproducible':True,'cursor_independent':True}))

# A rotated sparse mesh exposes the false contact made by transformed AABB corners.
mesh=bpy.data.meshes.new('Contact surface')
mesh.from_pydata([(0,0,0),(1,0,1),(0,1,1)],[],[(0,1,2)])
contact=bpy.data.objects.new('Contact',mesh)
contact.rotation_euler.y=math.radians(30)
collection=bpy.data.collections.new('Contact collection')
bpy.context.scene.collection.children.link(collection)
collection.objects.link(contact)
bpy.ops.mesh.primitive_cube_add(size=.1,location=(0,0,1))
visible=bpy.context.object
collection.objects.link(visible)
visible.parent=contact
build.blender_assets.align_collection_z(collection,contact,'bottom',-.2)
points=build.blender_assets.collection_world_points(collection)
assert math.isclose(min(p.z for p in points),-.2,abs_tol=1e-6)
# Explicit compact placements follow the pile rather than the former fan footprint.
build.place_stack_table_props({'layout':'stack','compact':{'prop_placements':{'prop':{'side':'above','gap':.04,'along':-.2}}}},
 {'prop':{'kind':'collection','root_object':contact.name,'transform':{'z_reference':'table'}}}, {'prop':collection})
points=build.blender_assets.collection_world_points(collection)
assert min(p.y for p in points)>2.53
camera=build.add_camera({'rotation_degrees':[45,0,-10],'lens':85})
build.frame_compact_stack(camera,{'layout':'stack','compact':{'outlier_fraction':0,'edge_curl':0}},{'prop':collection})
for p in points:
 view=world_to_camera_view(bpy.context.scene,camera,p)
 assert .01<view.x<.99 and .01<view.y<.99 and view.z>0,tuple(view)
print('CONTACT_AND_COMPOSITION_CHECK: passed')

# Correlated groups preserve the cover and produce a reproducible bounded contour.
reset(56)
build.build_stack(Path('/unused'),{'layout':'stack'},random.Random(2211024416))
first=signature()
outliers=[o for o in bpy.context.scene.objects if o.get('paper_stack_outlier')]
assert 4 < len(outliers) < 55
assert any(a['paper_index']+1==b['paper_index'] for a in outliers for b in outliers)
assert all(0<o['paper_index']<56 for o in outliers)
assert all(abs(o.location.x)<.010 and abs(o.location.y-2)<.010 for o in outliers)
curved=sorted(bpy.context.scene.objects,key=lambda o:o['paper_index'])
assert len(curved[0].data.vertices)>100
# Height is normalized independently of fixed shader strength.
assert curved[0]['paper_surface_amplitude']==1.0
assert curved[-1]['paper_surface_amplitude']==0
assert all(a['paper_surface_amplitude']>=b['paper_surface_amplitude'] for a,b in zip(curved,curved[1:]))
assert max(v.co.z for v in curved[0].data.vertices)>.002
assert max(abs(v.co.z) for v in curved[-1].data.vertices)<1e-8
# Check actual triangles over common XY points: layers must remain ordered.
bpy.context.view_layer.update()
for x in [-.32,-.15,0,.15,.32]:
 for y in [1.52,1.6,2,2.4,2.48]:
  previous=None
  for obj in curved:
   origin=obj.matrix_world.inverted()@Vector((x,y,1))
   hit,point,_,_=obj.ray_cast(origin,Vector((0,0,-1)))
   if not hit:continue
   z=(obj.matrix_world@point).z
   if previous is not None:assert previous-z>.00119,(obj.name,x,y,previous,z)
   previous=z
reset(56)
build.build_stack(Path('/unused'),{'layout':'stack'},random.Random(2211024416))
assert first==signature()
camera=build.add_camera({'rotation_degrees':[45,0,-10],'lens':85})
build.frame_compact_stack(camera,{'layout':'stack'})
focus=camera.data.dof.focus_object
assert focus.name=='Article title focus'
assert abs(focus.location.x)<1e-6 and abs(focus.location.y-2.26)<1e-6 and abs(focus.location.z)<1e-6
axis=camera.rotation_euler.to_matrix()@Vector((0,0,1))
assert math.isclose(camera.data.dof.focus_distance,(camera.location-focus.location).dot(axis),abs_tol=1e-5)
print('CORRELATED_CONTOUR_AND_TITLE_FOCUS_CHECK: passed')
