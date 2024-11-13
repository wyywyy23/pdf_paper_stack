import math
import os
import random

import bpy

paper = "spie23"

# Set random seed for reproducibility
random.seed(2441622110)

# Delete every thing in the startup scene
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

# Set the render engine to Cycles
bpy.context.scene.render.engine = "CYCLES"
# Config renderer to use GPU
bpy.context.scene.cycles.device = "GPU"
# Set viewport shading to rendered
bpy.context.space_data.shading.type = "RENDERED"

# Import images as planes
path = "img/" + paper
bpy.ops.preferences.addon_enable(module="io_import_images_as_planes")

z_offset = 0.001
z_position = 0

degree_rotate_max = 1.5

images = sorted(
    [img for img in os.listdir(path) if img.endswith(".png") or img.endswith(".jpg")]
)
degree_rotate = max(degree_rotate_max / len(images) * 8, degree_rotate_max)

for i, img in enumerate(images):
    bpy.ops.import_image.to_plane(files=[{"name": img}], directory=path)
    imported_object = bpy.context.selected_objects[0]
    imported_object.location.z = z_position
    z_position -= z_offset
    imported_object.data.materials[0].node_tree.nodes["Principled BSDF"].inputs[
        "Specular"
    ].default_value = 0
    imported_object.data.materials[0].node_tree.nodes["Principled BSDF"].inputs[
        "Roughness"
    ].default_value = 1
    imported_object.data.materials[0].node_tree.nodes["Principled BSDF"].inputs[
        "Transmission"
    ].default_value = 0.1
    # Add a node for mimicking paper texture
    material = imported_object.data.materials[0]
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    # Create a new texture node
    texture_node = nodes.new(type="ShaderNodeTexNoise")
    texture_node.inputs["Scale"].default_value = 200
    texture_node.inputs["Detail"].default_value = 10
    texture_node.inputs["Roughness"].default_value = 0.5

    # Create a bump node
    bump_node = nodes.new(type="ShaderNodeBump")
    bump_node.inputs["Strength"].default_value = 0.1

    # Link the texture node to the bump node
    links.new(texture_node.outputs["Fac"], bump_node.inputs["Height"])

    # Link the bump node to the Principled BSDF node
    principled_bsdf = nodes.get("Principled BSDF")
    links.new(bump_node.outputs["Normal"], principled_bsdf.inputs["Normal"])

    # Create a new texture node for macro scale noise
    macro_texture_node = nodes.new(type="ShaderNodeTexNoise")
    macro_texture_node.inputs["Scale"].default_value = 2
    macro_texture_node.inputs["Detail"].default_value = 1
    macro_texture_node.inputs["Roughness"].default_value = 0.5

    # Create another bump node for macro scale noise
    macro_bump_node = nodes.new(type="ShaderNodeBump")
    macro_bump_node.inputs["Strength"].default_value = 0.5

    # Link the macro texture node to the macro bump node
    links.new(macro_texture_node.outputs["Fac"], macro_bump_node.inputs["Height"])

    # Combine the macro bump with the existing bump
    combine_bump_node = nodes.new(type="ShaderNodeMixRGB")
    combine_bump_node.blend_type = "ADD"
    combine_bump_node.inputs["Fac"].default_value = 1.0

    links.new(bump_node.outputs["Normal"], combine_bump_node.inputs[1])
    links.new(macro_bump_node.outputs["Normal"], combine_bump_node.inputs[2])

    # Link the combined bump node to the Principled BSDF node
    links.new(combine_bump_node.outputs["Color"], principled_bsdf.inputs["Normal"])

    imported_object.location.y = imported_object.dimensions.y * 2
    # Rotate around object center
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY")
    bpy.ops.transform.rotate(value=math.radians(random.gauss(0, 1)), orient_axis="Z")
    # Rotate around origin cursor
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    bpy.ops.transform.rotate(
        value=math.radians(-degree_rotate * i + random.gauss(0, 0.2)), orient_axis="Z"
    )


# Add a background plane 1 z_offset below all imported planes
bpy.ops.mesh.primitive_plane_add(size=10, location=(0, 0, z_position - z_offset))
background_plane = bpy.context.object
background_plane.name = "BackgroundPlane"

# Add a clear glass block with the size of the background plane covering the planes
bpy.ops.mesh.primitive_cube_add(size=10, location=(0, 0, 0))
glass_block = bpy.context.object
glass_block.name = "GlassBlock"
glass_block.scale = (1, 1, (-z_position + z_offset + 50 * z_offset) / 10)
glass_block.location.z = (
    z_position - z_offset + glass_block.dimensions.z * glass_block.scale[2] / 2
)
glass_block.data.materials.append(bpy.data.materials.new(name="Glass"))
glass_material = glass_block.data.materials[0]
glass_material.use_nodes = True
if glass_material.node_tree.nodes.get("Principled BSDF"):
    glass_material.node_tree.nodes.remove(
        glass_material.node_tree.nodes.get("Principled BSDF")
    )
mat_output = glass_material.node_tree.nodes.get("Material Output")
glass_bsdf = glass_material.node_tree.nodes.new("ShaderNodeBsdfGlass")
glass_bsdf.inputs["Roughness"].default_value = 0
glass_bsdf.inputs["IOR"].default_value = 1.45
glass_bsdf.inputs["Color"].default_value = (0.6, 0.6, 0.6, 1)
glass_material.node_tree.links.new(mat_output.inputs[0], glass_bsdf.outputs[0])
glass_block.active_material = glass_material

# Change background plane color to gray with a matte finish
background_plane.data.materials.append(bpy.data.materials.new(name="Background"))
background_material = background_plane.data.materials[0]
background_material.use_nodes = True
background_material.node_tree.nodes["Principled BSDF"].inputs[
    "Base Color"
].default_value = (0.56, 0.77, 1, 1)
background_plane.data.materials[0].node_tree.nodes["Principled BSDF"].inputs[
    "Specular"
].default_value = 0
background_plane.data.materials[0].node_tree.nodes["Principled BSDF"].inputs[
    "Roughness"
].default_value = 1


# Add sky texture to world
sun_intensity = 1  # default is 1
sun_rotation = 45  # default is 0

world = bpy.data.worlds["World"]
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
sky = world.node_tree.nodes.new("ShaderNodeTexSky")
world.node_tree.links.new(sky.outputs[0], bg.inputs[0])
# set the sun intensity
sky.sun_intensity = sun_intensity
# set the sun rotation
sky.sun_rotation = sun_rotation * math.pi / 180

# Add camera
bpy.ops.object.camera_add()

x = -0.45
y = 0.65
z = 1.6
rx = 45
ry = 0
rz = -10
lens = 85
use_dof = True
focus_distance = 2.38
fstop = 2.8
samples = 1024
denoise = False

# Set camera location and rotation
bpy.context.object.location[0] = x
bpy.context.object.location[1] = y
bpy.context.object.location[2] = z
bpy.context.object.rotation_euler[0] = rx * math.pi / 180
bpy.context.object.rotation_euler[1] = ry * math.pi / 180
bpy.context.object.rotation_euler[2] = rz * math.pi / 180
# Set camera focal length
bpy.context.object.data.lens = lens
# enable depth of field
bpy.context.object.data.dof.use_dof = use_dof
# Set focus distance
bpy.context.object.data.dof.focus_distance = focus_distance
# Set f-stop
bpy.context.object.data.dof.aperture_fstop = fstop
# Align view to camera
bpy.ops.view3d.object_as_camera()

# Set to Standard and Very Low Contrast
bpy.context.scene.view_settings.view_transform = "Standard"
bpy.context.scene.view_settings.look = "Medium High Contrast"

# Set max samples in render
bpy.context.scene.cycles.samples = samples

# Disable render denoising
bpy.context.scene.cycles.use_denoising = denoise

# Set film to transparent
bpy.context.scene.render.film_transparent = True

# Save project file
bpy.ops.wm.save_as_mainfile(
    filepath="prj/{}_suni_{}_sunr_{}_x_{}_y_{}_z_{}_rx_{}_ry_{}_rz_{}_lens_{}_dof_{}_dist_{}_fstop_{}_samp_{}_denoise_{}.blend".format(
        paper,
        sun_intensity,
        sun_rotation,
        x,
        y,
        z,
        rx,
        ry,
        rz,
        lens,
        use_dof,
        focus_distance,
        fstop,
        samples,
        denoise,
    )
)
