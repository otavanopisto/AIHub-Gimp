# AIHub Support for GIMP

[Work in progress]

## Purpose

Comfy UI provides powerful workflow generations with many models that can be used to generate striking and powerful workflows, however these workflows are often not used to their full potential because they are often used solo rather than as AI assistance workflow.

The purpose of this plugin is to bring the following features, step by step in the following order, by leveraging gimp capabilities, and therefore this plugin will extend on GNU GIMP operations.

For that it is leveraged the AIHub protocol that was created as a comfyui plugin in order for it to be accessed all potential workflows that exist for comfyui and expose them into any application, this plugin does the implementation in GIMP.

Once this is enabled this will provide a framework to enable our local community to learn highly advanced AI tools and complex workflows more effectively without having to rely on knowing how to handle the high complexities of dealing with these checkpoints and loras directly, it provides a base; and since any workflow should be integrable later on, it means that as the user advances through they can create their own workflows and integrate them with GIMP too without making a new plugin or knowing how to code.

The primary point is to be able to educate people so they are able to handle these advanced tools without being experts in the field and therefore make courses and educational information.

### AI assisted image generation

Simple: AI assisted image creation that fits your vision more accurately using Gimp tools.

Most people are under the impression that image generation is just give a prompt and that is all, however this is but a merely simplified workflow; AI image generation can have further control and fine detail and therefore acting more of an assistant to bring a very specific vision to life, therefore this project aims to bring true AI assisted workflows where the inputs are, 1. a positive prompt 2. a negative prompt 3. any other arbitrary number of prompts 4. an image reference prompt that has to be either drawn in gimp or otherwise a reference picture. 5. a healing mask. 6. Arbitrary controls such as CFG, denoising, latent handling, model and applied loras; the way this will work is by adapting itself to comfy with modified workflows that are specifically edited to merge with GIMP.

This process will also include image upscaling.

### AI assisted character/object/environment generation

Simple: Create characters objects or environments and place them anywhere you want, consistently within the character creator.

Once AI assisted image generation has been tackled, a second objective is to be tackled, character generation, the purpose is to use a very specific flow using either SDXL or flux in order to generate characters and tensor references, as well as using WAN (yes a video one) to generate angles in order to build training sets; these characters can be reused and be consistent, the flow will produce a .safetensor file as output that is the character, object or environment; that is to be used among the model for consistent image generation.

This will allow creation of specific AI characters and for them to be possibly to be shared, so artists can now create characters as tensors; a process more involved than simply generating an image as it requires quite a bit of work and lots of references that can be made itself with the first process and by plenty of modification to fit an exact vision; then the resulting tensor will be able to replicate that effect consistently.

### AI Assisted video generation

Simple: Create movies and shorts consistently.

The last one to tackle is AI video generation, using the research by VACE and the outputs that they have given with WAN and LTX Video it may be possible to build a fully featured animation engine; only for scenes that is capable of running on home hardware, this is why the previous tricks are important, the previous tensors would be heavily relied upon to improve video consistency by using masking layers within VACE and determine flow.
