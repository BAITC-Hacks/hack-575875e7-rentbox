"""Original Windcast turbine. Run in Blender, or through execute_blender_code.

Rebuild: blender --background --python scripts/blender/create_wind_turbine.py
The GLB is a visual illustration, not an engineering model of the case turbines.
"""
import bpy
import math
import sys
from pathlib import Path
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "apps" / "web" / "public" / "models"
SOURCE = ROOT / "assets" / "blender"
PUBLIC.mkdir(parents=True, exist_ok=True)
SOURCE.mkdir(parents=True, exist_ok=True)

# Replace only previous generated asset scenes; keep unrelated user scenes intact.
previous_scenes = [s for s in bpy.data.scenes if s.name == 'Windcast Turbine' or s.name.startswith('Windcast Turbine.')]
scene = bpy.data.scenes.new('Windcast Turbine')
bpy.context.window.scene = scene
for previous_scene in previous_scenes:
    for old_object in list(previous_scene.objects):
        if len(old_object.users_scene) == 1:
            bpy.data.objects.remove(old_object, do_unlink=True)
    bpy.data.scenes.remove(previous_scene)
scene.name = 'Windcast Turbine'
bpy.context.window.scene = scene
model = bpy.data.collections.new("Windcast_Model")
scene.collection.children.link(model)
studio = bpy.data.collections.new("Studio")
scene.collection.children.link(studio)

def material(name, color, metallic=0.0, roughness=0.4):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Metallic'].default_value = metallic
    shader.inputs['Roughness'].default_value = roughness
    return mat

white = material('Porcelain | warm white', (.88,.91,.86), .15,.3)
olive = material('Windcast | deep olive', (.075,.15,.095), .25,.38)
sage = material('Blade tips | sage', (.35,.48,.24), .08,.4)
stone = material('Foundation | limestone', (.69,.73,.63), .0,.72)
seam = material('Brushed metal', (.36,.43,.36), .65,.32)
dark = material('Technical graphite', (.045,.065,.055), .4,.32)
beacon = material('Amber beacon', (.95,.46,.07), .1,.28)

def move_to(obj, collection=model):
    for current in list(obj.users_collection):
        current.objects.unlink(obj)
    collection.objects.link(obj)
    return obj

def finish(obj, name, mat, bevel=0, smooth=True):
    obj.name = name
    move_to(obj)
    obj.data.materials.append(mat)
    if smooth and obj.type == 'MESH':
        for poly in obj.data.polygons:
            poly.use_smooth = True
    if bevel:
        mod = obj.modifiers.new('Soft manufactured edges','BEVEL')
        mod.width = bevel
        mod.segments = 3
        obj.modifiers.new('Weighted normals','WEIGHTED_NORMAL')
    return obj

def cylinder(name, radius, depth, location, mat, top=None, bevel=.025):
    bpy.ops.mesh.primitive_cone_add(vertices=64, radius1=radius, radius2=radius if top is None else top, depth=depth, location=location)
    return finish(bpy.context.object,name,mat,bevel)

def box(name, dims, location, mat, bevel=.04):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj=bpy.context.object
    obj.dimensions=dims
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish(obj,name,mat,bevel,False)

def sphere(name, scale, location, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=40,ring_count=20,location=location)
    obj=bpy.context.object
    obj.scale=scale
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    return finish(obj,name,mat)

cylinder('Foundation | olive floating edge',2.15,.17,(0,0,.085),olive,bevel=.07)
cylinder('Foundation | limestone deck',2.10,.22,(0,0,.265),stone,bevel=.07)
cylinder('Tower | anchor flange',.64,.13,(0,0,.435),white,bevel=.03)
for i in range(12):
    angle=math.tau*i/12
    cylinder(f'Anchor bolt {i+1:02}',.025,.06,(.51*math.cos(angle),.51*math.sin(angle),.53),seam,bevel=.005)
cylinder('Tower | tapered shell',.39,9.7,(0,0,5.35),white,top=.24,bevel=.03)
for z in (3.5,6.8):
    radius=.39-(z-.5)/9.7*.15
    cylinder(f'Tower | joint {z}',radius+.008,.023,(0,0,z),seam,bevel=.003)
box('Tower | service door',(.32,.043,.82),(0,-.373,1.0),olive,.075)
box('Tower | door inset',(.25,.045,.66),(0,-.404,1.02),dark,.055)
box('Tower | handle',(.018,.035,.11),(.08,-.437,1.03),seam,.006)
box('Tower | access step',(.46,.42,.07),(0,-.6,.47),seam,.025)
cylinder('Yaw bearing',.34,.19,(0,0,10.22),dark,bevel=.025)
box('Nacelle | aerodynamic housing',(.99,2.05,.77),(0,.34,10.64),white,.23)
box('Nacelle | lower olive belt',(1.004,1.57,.17),(0,.40,10.43),olive,.07)
box('Nacelle | rear grille',(.66,.06,.36),(0,1.366,10.62),dark,.08)
for index in range(7):
    box(f'Rear vent {index}',(.47,.065,.016),(0,1.405,10.49+index*.04),seam,.005)
box('Nacelle | side badge',(.023,.35,.13),(.506,.70,10.71),sage,.025)
cylinder('Roof | beacon foot',.09,.055,(0,.91,11.04),dark,bevel=.01)
sphere('Roof | amber beacon',(.063,.063,.08),(0,.91,11.10),beacon)
cylinder('Roof | anemometer mast',.022,.33,(0,.18,11.16),seam,bevel=.005)
for i in range(3):
    a=math.tau*i/3
    sphere(f'Anemometer cup {i}',(.06,.06,.035),(.14*math.cos(a),.18+.14*math.sin(a),11.33),dark)
    arm=box(f'Anemometer arm {i}',(.14,.017,.017),(.07*math.cos(a),.18+.07*math.sin(a),11.33),seam,.005)
    arm.rotation_euler.z=a

rotor=bpy.data.objects.new('Rotor',None)
model.objects.link(rotor)
rotor.location=(0,-.90,10.64)
rotor['purpose']='Illustrative animation; not measured turbine RPM'
hub=sphere('Rotor | sculpted spinner',(.46,.52,.46),(0,0,0),white)
hub.parent=rotor
hub.location=(0,-.20,0)
hub_ring=cylinder('Rotor | root collar',.405,.11,(0,0,0),olive,bevel=.02)
hub_ring.parent=rotor
hub_ring.location=(0,.12,0)
hub_ring.rotation_euler.x=math.pi/2

# Closed, twisted and swept airfoil sections; three copies share one geometry.
vertices=[]
faces=[]
RINGS=25
SIDES=24
for ring in range(RINGS):
    t=ring/(RINGS-1)
    radius=.38+4.82*t
    chord=(.21+.92*math.sin(math.pi*min(t*1.25,1))**.75)*(1-.73*t)+.015
    if ring==RINGS-1:
        chord=.018
    center=.04+.54*t*t
    thickness=max(.012,chord*.13)
    twist=math.radians(13*(1-t))
    for side in range(SIDES):
        angle=math.tau*side/SIDES
        x=chord*.5*math.cos(angle)
        y=thickness*math.sin(angle)*(.78+.22*math.cos(angle))
        vertices.append((center+x*math.cos(twist)-y*math.sin(twist),x*math.sin(twist)+y*math.cos(twist),radius))
for ring in range(RINGS-1):
    for side in range(SIDES):
        a=ring*SIDES+side
        b=ring*SIDES+(side+1)%SIDES
        faces.append((a,b,b+SIDES,a+SIDES))
faces.append(tuple(reversed(range(SIDES))))
faces.append(tuple((RINGS-1)*SIDES+i for i in range(SIDES)))
mesh=bpy.data.meshes.new('Windcast swept airfoil')
mesh.from_pydata(vertices,[],faces)
mesh.materials.append(white)
mesh.materials.append(sage)
for polygon in mesh.polygons:
    polygon.use_smooth=True
    if polygon.index//SIDES >= RINGS-4 and len(polygon.vertices)==4:
        polygon.material_index=1
for i in range(3):
    blade=bpy.data.objects.new(f'Blade_{i+1:02}',mesh)
    model.objects.link(blade)
    blade.parent=rotor
    blade.rotation_euler.y=math.tau*i/3 + math.radians(-13)

# Stylized geared drivetrain. These are explanatory components, not SCADA geometry.
copper = material('Generator | copper', (.64,.29,.105), .72,.3)
steel_blue = material('Gearbox | blue steel', (.15,.33,.39), .55,.28)
shaft = cylinder('Internal_MainShaft',.095,1.14,(0,-.22,10.64),seam,bevel=.012)
shaft.rotation_euler.x=math.pi/2
box('Internal_Bedplate',(.72,1.76,.07),(0,.35,10.32),dark,.025)
gearcase=box('Internal_Gearbox',(.53,.49,.48),(0,.25,10.61),steel_blue,.065)
for gi in range(3):
    gear=cylinder(f'Internal_Gear_{gi}',.17-gi*.025,.065,(.285,.12+gi*.13,10.66),copper,bevel=.008)
    gear.rotation_euler.y=math.pi/2
    for tooth in range(10):
        a=math.tau*tooth/10
        box(f'Internal_Tooth_{gi}_{tooth}',(.075,.046,.046),(.285,.12+gi*.13+(.17-gi*.025)*math.cos(a),10.66+(.17-gi*.025)*math.sin(a)),copper,.005)
generator=cylinder('Internal_Generator',.235,.52,(0,.87,10.62),copper,bevel=.025)
generator.rotation_euler.x=math.pi/2
for index in range(6):
    ring=cylinder(f'Internal_GeneratorFin_{index}',.25,.018,(0,.66+index*.078,10.62),dark,bevel=.003)
    ring.rotation_euler.x=math.pi/2
box('Internal_Converter',(.24,.29,.24),(.24,1.10,10.47),olive,.025)
for obj in model.objects:
    if obj.name.startswith('Internal_'):
        obj['purpose']='Illustrative geared drivetrain; shown in cutaway view only'

# Low relief landscape details around the circular foundation.
for i,(x,y,s) in enumerate([(-1.2,.9,.5),(1.2,.9,.4),(1.0,-1.2,.28)]):
    sphere(f'Landscape | planting mound {i}',(s,s*.65,.055),(x,y,.39),sage)
for i in range(4):
    box(f'Foundation | walkway {i}',(.50,.18,.025),(0,-.95-i*.21,.385),white,.025)

# Export geometry only. Studio lights and camera remain in the editable blend file.
bpy.ops.object.select_all(action='DESELECT')
for obj in model.objects:
    obj.select_set(True)
bpy.context.view_layer.objects.active = next(obj for obj in model.objects if obj.type=='MESH')
bpy.ops.export_scene.gltf(filepath=str(PUBLIC/'windcast-turbine.glb'),export_format='GLB',use_selection=True,export_apply=True,export_animations=False,export_cameras=False,export_lights=False)

world=bpy.data.worlds.new('Soft daylight')
scene.world=world
world.use_nodes=True
world.node_tree.nodes['Background'].inputs['Color'].default_value=(.79,.84,.73,1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value=.35

def area(name,position,energy,size,color):
    data=bpy.data.lights.new(name,'AREA')
    data.energy=energy
    data.shape='DISK'
    data.size=size
    data.color=color
    obj=bpy.data.objects.new(name,data)
    studio.objects.link(obj)
    obj.location=position
    obj.rotation_euler=(Vector((0,0,7))-obj.location).to_track_quat('-Z','Y').to_euler()
area('Key | softbox',(7,-10,18),2100,9,(1,.96,.86))
area('Fill | cool sky',(-7,-2,12),1500,8,(.82,.91,1))
area('Rim | sunlight',(3,8,17),2600,7,(1,1,.90))
cam_data=bpy.data.cameras.new('Windcast portrait')
cam=bpy.data.objects.new('Camera | hero',cam_data)
studio.objects.link(cam)
cam.location=(14,-26,15)
cam.rotation_euler=(Vector((0,0,7.4))-cam.location).to_track_quat('-Z','Y').to_euler()
cam_data.type='ORTHO'
cam_data.ortho_scale=18.3
scene.camera=cam
scene.render.engine='CYCLES'
scene.cycles.samples=32
scene.cycles.use_denoising=True
scene.render.resolution_x=1000
scene.render.resolution_y=1000
scene.render.resolution_percentage=100
scene.render.film_transparent=True
scene.render.image_settings.file_format='PNG'
scene.render.image_settings.color_mode='RGBA'
scene.render.filepath=str(PUBLIC/'windcast-turbine.png')
scene.view_settings.view_transform='AgX'
for screen in bpy.data.screens:
    for a in screen.areas:
        if a.type=='VIEW_3D':
            a.spaces.active.region_3d.view_perspective='CAMERA'
            a.spaces.active.shading.type='MATERIAL'
bpy.ops.wm.save_as_mainfile(filepath=str(SOURCE/'windcast-turbine.blend'))
print('WINDCAST_ASSETS_EXPORTED',len(model.objects),'objects')
if '--render' in sys.argv:
    bpy.ops.render.render(write_still=True)
