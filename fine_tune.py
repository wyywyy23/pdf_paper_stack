import math
import random

import bpy

# Add wood and pen manually
# Oak wood
# asset_base_id:752306e7-fb72-4a84-89a1-3be404dcdc38 asset_type:material
# Fountain pen
# asset_base_id:8328e08e-3773-4b25-bf10-8380d9131cca asset_type:model
# Paper clip
# asset_base_id:901330d6-d5e1-468d-8365-d5707590a274 asset_type:model

# Deselect all and select the Fountain Pen object
bpy.ops.object.select_all(action="DESELECT")
bpy.data.objects["Fountain Pen"].select_set(True)
bpy.context.view_layer.objects.active = bpy.data.objects["Fountain Pen"]
# Set x: 0.2, y: 2, rz: 270, scale_x: -0.08, scale_y: -0.08, scale_z: -0.08
bpy.context.object.location[0] = 0.2 + random.gauss(0, 0.02)
bpy.context.object.location[1] = 2 + random.gauss(0, 0.02)
bpy.context.object.rotation_euler[2] = math.radians(270 + random.gauss(0, 5))
bpy.context.object.scale[0] = -0.08
bpy.context.object.scale[1] = -0.08
bpy.context.object.scale[2] = -0.08

# Deselect all and select the Paper clip object
bpy.ops.object.select_all(action="DESELECT")
bpy.data.objects["Paper clip"].select_set(True)
bpy.context.view_layer.objects.active = bpy.data.objects["Paper clip"]
# Set x: -0.5, y: 2.6, rz: 200, scale_x: 0.006, scale_y: 0.006, scale_z: 0.006
bpy.context.object.location[0] = -0.5 + random.gauss(0, 0.02)
bpy.context.object.location[1] = 2.6 + random.gauss(0, 0.02)
bpy.context.object.rotation_euler[2] = math.radians(200 + random.gauss(0, 5))
bpy.context.object.scale[0] = 0.006
bpy.context.object.scale[1] = 0.006
bpy.context.object.scale[2] = 0.006
