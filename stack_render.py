import math
import os
import random

import bpy

paper = "ofc23"

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

z_offset = 0.0005
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
    texture_node.inputs["Scale"].default_value = 500
    texture_node.inputs["Detail"].default_value = 250
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
    macro_texture_node.inputs["Scale"].default_value = 1.5
    macro_texture_node.inputs["Detail"].default_value = 0.5
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

# Add wood manually
# asset_base_id:752306e7-fb72-4a84-89a1-3be404dcdc38 asset_type:material

# Add a soft white light at (5, 5, 5)
bpy.ops.object.light_add(type="SPOT", location=(-5, 5, 5))
light = bpy.context.object
light.data.energy = 2000
light.data.color = (0.956, 0.839, 0.761)
light.data.spot_size = math.radians(45)
light.data.spot_blend = 0.15
light.rotation_euler[0] = math.radians(-34)
light.rotation_euler[1] = math.radians(-37)
light.rotation_euler[2] = math.radians(15)

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
fstop = 1.8
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
bpy.context.scene.view_settings.view_transform = "Filmic"
bpy.context.scene.view_settings.look = "Very High Contrast"

# Set max samples in render
bpy.context.scene.cycles.samples = samples

# Disable render denoising
bpy.context.scene.cycles.use_denoising = denoise

# Set film to transparent
bpy.context.scene.render.film_transparent = True

# Save project file
bpy.ops.wm.save_as_mainfile(
    filepath="prj/{}_x_{}_y_{}_z_{}_rx_{}_ry_{}_rz_{}_lens_{}_dof_{}_dist_{}_fstop_{}_samp_{}_denoise_{}.blend".format(
        paper,
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
