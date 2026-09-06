TypeMap:
	# Non-mergeable DCC source and binary delivery files: exclusive checkout.
	binary+l //....fbx
	binary+l //....FBX
	binary+l //....blend
	binary+l //....blend1
	binary+l //....ma
	binary+l //....mb
	binary+l //....max
	binary+l //....psd
	binary+l //....psb
	binary+l //....tif
	binary+l //....tiff
	binary+l //....exr
	binary+l //....wav
	binary+l //....aif
	binary+l //....aiff
	binary+l //....mp3
	binary+l //....ogg
	binary+l //....mp4
	binary+l //....mov

	# Imported binary textures: binary history, parallel edits allowed when practical.
	binary //....png
	binary //....jpg
	binary //....jpeg
	binary //....tga
	binary //....dds

	# Unity YAML assets remain text but use exclusive checkout in this learning workflow.
	text+l //....unity
	text+l //....prefab
	text+l //....asset
	text+l //....controller
	text+l //....overrideController
	text+l //....anim
	text+l //....mat

	# Source/config files remain mergeable text.
	text //....meta
	text //....cs
	text //....asmdef
	text //....json
	text //....yaml
	text //....yml
	text //....txt
	text //....md
