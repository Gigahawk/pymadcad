# This file is part of pymadcad,  distributed under license LGPL v3

'''	Display module of pymadcad
	
	This module provides a render pipeline system centered around class 'Scene' and a Qt widget 'View' for window integration and user interaction. 'Scene' is only to manage the objects to render (almost every madcad object). Most of the time you won't need to deal with it directly. The widget is what actually displays it on the screen.
	The objects displayed can be of any type but must implement the display protocol
	
	display protocol
	----------------
		a displayable is an object that implements the signatue of Display:
		
			class display:
				box (Box)                      delimiting the display, can be an empty or invalid box
				pose (fmat4)                    local transformation
				
				stack(scene)                   rendering routines (can be methods, or any callable)
				duplicate(src,dst)             copy the display object for an other scene if possible
				upgrade(scene,displayable)     upgrade the current display to represent the given displayable
				control(...)                   handle events
				
				__getitem__                    access to subdisplays if there is
		
		For more details, see class Display below
	
	NOTE
	----
		There is some restrictions using the widget. This is due to some Qt limitations (and design choices), that Qt is using separated opengl contexts for each independent widgets or window.
		
		- a View should not be reparented once displayed
		- a View can't share a scene with Views from an other window
		- to share a Scene between Views, you must activate 
				QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
'''

from copy import copy, deepcopy

import moderngl as mgl
import numpy.core as np

from PyQt5.QtCore import Qt, QPoint, QEvent
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtGui import QSurfaceFormat, QMouseEvent, QInputEvent, QKeyEvent, QTouchEvent

from .mathutils import (fvec3, fvec4, fmat3, fmat4, fquat, vec3, Box, mat4_cast, mat3_cast,
						sin, cos, tan, atan2, pi, inf,
						length, project, noproject, transpose, inverse, affineInverse, 
						perspective, ortho, translate, 
						bisect, boundingbox,
						)
from .common import ressourcedir
from . import settings

from .nprint import nprint


# minimum opengl required version
opengl_version = (3,3)



def show(objs, options=None, interest=None):
	''' shortcut to create a QApplication showing only one view with the given objects inside.
		the functions returns when the window has been closed and all GUI destroyed
	'''
	if isinstance(objs, list):	objs = dict(enumerate(objs))
	
	import sys
	from PyQt5.QtCore import Qt, QCoreApplication
	from PyQt5.QtWidgets import QApplication
	
	QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
	app = QApplication(sys.argv)
	
	# use the Qt color scheme if specified
	if settings.display['system_theme']: 
		settings.use_qt_colors()
	
	# create the scene as a window
	view = View(Scene(objs, options))
	view.show()
	
	# make the camera see everything
	if not interest:	interest = view.scene.box()
	view.center()
	view.adjust()
	
	err = app.exec()
	if err != 0:	print('error: Qt exited with code', err)


class Display:
	''' Blanket implementation for displays.
		This class signature is exactly the display protocol specification
	'''
	
	# mendatory part of the protocol
	
	box = Box(center=0, width=fvec3(-inf))	# to inform the scene and the view of the object size
	world = fmat4(1)		# set by the display containing this one if it is belonging to a group
	
	def display(self, scene) -> 'self':
		''' displays are obviously displayable as themselves '''
		return self
	def stack(self, scene) -> '[(key, target, priority, callable)]':
		''' rendering functions to insert in the renderpipeline 
			callables is provided the used view as argument. The view contains the uniforms, rendering targets and the scene for common ressources
		'''
		return ()
	def duplicate(self, src, dst) -> 'display/None':
		''' duplicate the display for an other scene (other context) but keeping the same memory buffers when possible '''
		return None
	def __getitem__(self, key) -> 'display':
		''' get a subdisplay by its index/key in this display (like in a scene) '''
		raise IndexError('{} has no sub displays'.format(type(self).__name__))
	def update(self, scene, displayable) -> bool:
		''' update the current displays internal datas with the given displayable 
			if the display cannot be upgraded, it must return False to be replaced by a fresh new display created from the displayable
		'''
		return False
	
	# optional part for usage with Qt
	
	selected = False
	
	def control(self, scene, key, sub, evt: 'QEvent'):
		''' handle input events occuring on the area of this display (or of one of its subdisplay).
			for subdisplay events, the parents control functions are called first, and the sub display controls are called only if the event is not accepted by parents
			
			:key:    the key path for the current display
			:sub:    the key path for the subdisplay
		'''
		pass

def qt2glm(v):
	if isinstance(v, (QPoint, QPointF)):	return vec2(v.x(), v.y())
	elif isinstance(v, (QSize, QSizeF)):	return vec2(v.width(), v.height())
	else:
		raise TypeError("can't convert {} to vec2".format(type(v)))

def navigation_tool(dispatcher, view):
	''' internal navigation tool '''	
	ctrl = alt = slow = False
	curr = None
	while True:
		evt = yield
		if isinstance(evt, QKeyEvent):
			k = evt.key()
			press = evt.type() == QEvent.KeyPress
			if	 k == Qt.Key_Control:	ctrl = press
			elif k == Qt.Key_Alt:		alt = press
			elif k == Qt.Key_Shift:		slow = press
			if ctrl and alt:		curr = 'zoom'
			elif ctrl:				curr = 'pan'
			elif alt:				curr = 'rotate'
			else:					curr = None
			evt.accept()
		elif evt.type() == QEvent.MouseButtonPress:
			last = evt.pos()
			if evt.button() == Qt.MiddleButton:
				nav = 'rotate'
			else:
				nav = curr
		elif evt.type() == QEvent.MouseMove:
			if nav:
				gap = evt.pos() - last
				dx = gap.x()/view.height()
				dy = gap.y()/view.height()
				if nav == 'pan':		view.navigation.pan(dx, dy)
				elif nav == 'rotate':	view.navigation.rotate(dx, dy, 0)
				elif nav == 'zoom':		
					middle = QPoint(view.width(), view.height())/2
					f = (	(last-middle).manhattanLength()
						/	(evt.pos()-middle).manhattanLength()	)
					view.navigation.zoom(f)
				view.update()
				last = evt.pos()
				evt.accept()
				
		elif isinstance(evt, QTouchEvent):
			pts = evt.touchPoints()
			if len(pts) == 2:
				startlength = (pts[0].lastPos()-pts[1].lastPos()).manhattanLength()
				zoom = startlength / (pts[0].pos()-pts[1].pos()).manhattanLength()
				displt = (	(pts[0].pos()+pts[1].pos()) /2 
						-	(pts[0].lastPos()+pts[1].lastPos()) /2 ) /view.height()
				dc = pts[0].pos() - pts[1].pos()
				dl = pts[0].lastPos() - pts[1].lastPos()
				rot = atan2(dc.y(), dc.x()) - atan2(dl.y(), dl.x())
				view.navigation.zoom(zoom)
				view.navigation.rotate(displt.x(), displt.y(), rot)
				view.update()
				evt.accept()
			elif len(pts) == 3:
				lc = (	pts[0].lastPos() 
					+	pts[1].lastPos() 
					+	pts[2].lastPos() 
					)/3
				lr = (	(pts[0].lastPos() - lc) .manhattanLength()
					+	(pts[1].lastPos() - lc) .manhattanLength()
					+	(pts[2].lastPos() - lc) .manhattanLength()
					)/3
				cc = (	pts[0].pos() 
					+	pts[1].pos() 
					+	pts[2].pos() 
					)/3
				cr = (	(pts[0].pos() - cc) .manhattanLength()
					+	(pts[1].pos() - cc) .manhattanLength()
					+	(pts[2].pos() - cc) .manhattanLength()
					)/3
				zoom = lr / cr
				displt = (cc - lc)  /view.height()
				view.navigation.zoom(zoom)
				view.navigation.pan(displt.x(), displt.y())
				view.update()
				evt.accept()
				

class Turntable:
	def __init__(self, center:fvec3=0, distance:float=1, yaw:float=0, pitch:float=0):
		self.center = fvec3(center)
		self.yaw = yaw
		self.pitch = pitch
		self.distance = distance
		self.tool = navigation_tool
		
	def rotate(self, dx, dy, dz):
		self.yaw += dx*pi
		self.pitch += dy*pi
		if self.pitch > pi/2:	self.pitch = pi/2
		if self.pitch < -pi/2:	self.pitch = -pi/2
	def pan(self, dx, dy):
		mat = transpose(mat3_cast(inverse(fquat(fvec3(pi/2-self.pitch, 0, -self.yaw)))))
		self.center += ( mat[0] * -dx + mat[1] * dy) * self.distance/2
	def zoom(self, f):
		self.distance *= f
	
	def matrix(self) -> fmat4:
		# build rotation from view euler angles
		rot = inverse(fquat(fvec3(pi/2-self.pitch, 0, -self.yaw)))
		mat = translate(mat4_cast(rot), -self.center)
		mat[3][2] -= self.distance
		return mat

class Orbit:
	def __init__(self, center:fvec3=0, distance:float=1, orient:fvec3=fvec3(1,0,0)):
		self.center = fvec3(center)
		self.distance = float(distance)
		self.orient = fquat(orient)
		self.tool = navigation_tool
		
	def rotate(self, dx, dy, dz):
		# rotate from view euler angles
		self.orient = inverse(fquat(fvec3(-dy, -dx, dz) * pi)) * self.orient
	def pan(self, dx, dy):
		x,y,z = transpose(mat3_cast(self.orient))
		self.center += (fvec3(x) * -dx + fvec3(y) * dy) * self.distance/2
	def zoom(self, f):
		self.distance *= f
	
	def matrix(self) -> fmat4:
		mat = translate(mat4_cast(self.orient), -self.center)
		mat[3][2] -= self.distance
		return mat


class Perspective:
	def __init__(self, fov=None):
		self.fov = fov or settings.display['field_of_view']
	def matrix(self, ratio, distance) -> fmat4:
		return perspective(self.fov, ratio, distance*1e-2, distance*1e4)
class Orthographic:
	def matrix(self, ratio, distance) -> fmat4:
		return fmat4(1/ratio/distance, 0, 0, 0,
		            0,       1/distance, 0, 0,
		            0,       0,          1, 0,
		            0,       0,          0, 1)


class Scene:
	''' rendeing pipeline for madcad displayable objects 
		
		This class is gui-agnostic, it only relys on opengl, and the context has to be created by te user.
	'''
	
	def __init__(self, objs=(), options=None, ctx=None, setup=None):
		# context variables
		self.ctx = ctx
		self.ressources = {}	# context-related ressources, shared across displays, but not across contexts (shaders, vertexarrays, ...)
		
		# rendering options
		self.options = deepcopy(settings.scene)
		if options:	self.options.update(options)
		
		# render elements
		self.setup = setup or {}	# callable for each target
		self.queue = {}	# list of objects to display, not yet loaded on the GPU
		self.displays = {} # displays created from the inserted objects, associated to their insertion key
		self.stacks = {}	# dict of list of callables, that constitute the render pipeline:  (key,  priority, callable)
		
		self.touched = False
		self.update(objs)
	
	# methods to manage the rendering pipeline
	
	def add(self, displayable, key=None) -> 'key':
		''' add a displayable object to the scene, if key is not specified, an unused integer key is used 
			the object is not added to the the renderpipeline yet, but queued for next rendering.
		'''
		if key is None:
			for i in range(len(self.displays)+1):
				if i not in self.displays:	key = i
		self.queue[key] = displayable
		return key

	def __setitem__(self, key, value):
		''' equivalent with self.add with a key '''
		self.queue[key] = value
	def __getitem__(self, key) -> 'display':
		''' get the displayable for the given key, raise when there is no object or when the object is still in queue. '''
		return self.displays[key]
	def __delitem__(self, key):
		if key in self.displays:
			del self.displays[key]
		if key in self.queue:
			del self.queue[key]
		for stack in self.stacks.values():
			for i in reversed(range(len(stack))):
				if stack[i][0][0] == key:
					self.stacks.pop(i)
					
	def item(self, key):
		disp = self.displays
		for i in range(1,len(key)):
			disp = disp[key[i-1]]
		return disp
	
	def update(self, objs:dict):
		''' rebuild the scene from a dictionnary of displayables 
			update former displays if possible instead of replacing it
		'''
		self.queue.update(objs)
	
	def sync(self, objs:dict):
		''' update the scene from a dictionnary of displayables, the former values that cannot be updated are discarded '''
		for key in objs:
			if key not in self.displays:
				del self.displays[key]
		self.update(objs)
	
	def touch(self):
		self.touched = True
		
	def dequeue(self):
		''' load all pending objects to insert into the scene '''
		if self.queue:
			self.ctx.finish()
			# update displays
			for key,displayable in self.queue.items():
				if key not in self.displays or not self.displays[key].update(self, displayable):
					self.displays[key] = self.display(displayable)
			self.touched = True
			self.queue.clear()
		
		if self.touched:
			# recreate stack
			self.stacks.clear()
			for key,display in self.displays.items():
				for frame in display.stack(self):
					if len(frame) != 4:
						raise ValueError('wrong frame format in the stack from {}\n\t got {}'.format(display, frame))
					sub,target,priority,func = frame
					if target not in self.stacks:	self.stacks[target] = []
					stack = self.stacks[target]
					stack.insert(
								bisect(stack, priority, lambda s:s[1]), 
								((key,*sub), priority, func))
			self.touched = False
			#nprint(self.stacks)
	
	def render(self, view):
		''' render to the view targets '''
		empty = ()
		with self.ctx:
			# apply changes that need opengl runtime
			self.dequeue()
			# render everything
			for target, frame, setup in view.targets:
				view.target = frame
				frame.use()
				setup()
				for key, priority, func in self.stacks.get(target,empty):
					func(view)
	
	def box(self):
		''' computes the boundingbox of the scene, with the current object poses '''
		box = Box(center=fvec3(0), width=fvec3(-inf))
		for display in self.displays.values():
			box.union(display.box.transform(display.world))
		return box
	
	def ressource(self, name, func=None):
		''' get a ressource loaded or load it using the function func.
			If func is not provided, an error is raised
		'''
		if name in self.ressources:	
			return self.ressources[name]
		elif callable(func):
			with self.ctx as ctx:  # set the scene context as current opengl context
				res = func(self)
				self.ressources[name] = res
				return res
		else:
			raise KeyError("ressource {} doesn't exist or is not loaded".format(repr(name)))
					
	def display(self, obj):
		''' create a display for the given object for the current scene 
			you don't need to call this method if you just want to add an object to the scene, use add() instead
		'''
		if type(obj) in overrides:
			disp = overrides[type(obj)](obj, self)
		elif hasattr(obj, 'display'):
			disp = obj.display(self)
		else:
			raise TypeError('the type {} is displayable'.format(type(obj)))
		
		if not isinstance(disp, Display):
			raise TypeError('the display for {} is not a subclass of Display: {}'.format(type(obj), disp))
		return disp
	

def displayable(obj):
	''' return True if the given object has the matching signature to be added to a Scene '''
	return type(obj) in overrides or hasattr(obj, 'display')


class Step(Display):
	''' simple display holding a rendering stack step 
		Step(target, priority, callable)
	'''
	def __init__(self, *args):	self.step = ((), *args)
	def stack(self, scene):		return self.step,

class Displayable:
	def __init__(self, build, *args, **kwargs):
		self.args, self.kwargs = args, kwargs
		self.build = build
	def display(self, scene):
		return self.build(scene, *self.args, **self.kwargs)


def writeproperty(func):
	fieldname = '_'+func.__name__
	def getter(self):	return getattr(self, fieldname)
	def setter(self, value):
		setattr(self, fieldname, value)
		func(self, value)
	return property(getter, setter)

class Group(Display):
	''' a group is like a subscene '''
	def __init__(self, scene, objs:'dict/list'=None, pose=1):
		self._pose = fmat4(pose)
		self._world = fmat4(1)
		self.displays = {}
		if objs:	self.update(scene, objs)
	
	def __getitem__(self, key):
		return self.displays[key]
	def update(self, scene, objs):
		if isinstance(objs, dict):		items = objs.items()
		else:							items = enumerate(objs)
		# update displays
		with scene.ctx:
			scene.ctx.finish()
			for key, displayable in items:
				if key not in self.displays or not self.displays[key].update(self, displayable):
					self.displays[key] = scene.display(displayable)
		scene.touch()
	
	def stack(self, scene):
		for key,display in self.displays.items():
			for sub,target,priority,func in display.stack(scene):
				yield ((key, *sub), target, priority, func)
	
	@writeproperty
	def pose(self, pose):
		sub = self._world * self._pose
		for display in self.displays.values():
			display.world = sub
			
	@writeproperty
	def world(self, world):
		sub = self._world * self._pose
		for display in self.displays.values():
			display.world = sub
			
	@property
	def box(self):
		''' computes the boundingbox of the scene, with the current object poses '''
		box = Box(center=fvec3(0), width=fvec3(-inf))
		for display in self.displays.values():
			box.union(display.box.transform(display.world))
		return box


# dictionnary to store procedures to override default object displays
overrides = {}
overrides[list] = Group


class View(QOpenGLWidget):
	''' Qt widget to render and interact with displayable objects 
		it holds a scene as renderpipeline
	'''
	def __init__(self, scene, projection=None, navigation=None, parent=None):
		# super init
		super().__init__(parent)
		fmt = QSurfaceFormat()
		fmt.setVersion(*opengl_version)
		fmt.setProfile(QSurfaceFormat.CoreProfile)
		fmt.setSamples(4)
		self.setFormat(fmt)
		self.setFocusPolicy(Qt.StrongFocus)
		self.setAttribute(Qt.WA_AcceptTouchEvents, True)
		
		# interaction methods
		self.projection = projection or globals()[settings.scene['projection']]()
		self.navigation = navigation or globals()[settings.controls['navigation']]()
		self.tool = [Tool(self.navigation.tool, self)] # tool stack, the last tool is used for input events, until it is removed 
		
		# render parameters
		self.scene = scene if isinstance(scene, Scene) else Scene(scene)
		self.uniforms = {'proj':fmat4(1), 'view':fmat4(1), 'projview':fmat4(1)}	# last frame rendering constants
		self.targets = []
		self.steps = []
		self.step = 0
		self.stepi = 0
		
		# dump targets
		self.map_depth = None
		self.map_idents = None
		self.fresh = set()	# set of refreshed internal variables since the last render
	
	# -- internal frame system --
	
	def init(self):
		w,h = self.width(), self.height()
		ctx = self.scene.ctx
		assert ctx, 'context is not initialized'

		# self.fb_frame is already created and sized by Qt
		self.fb_screen = ctx.detect_framebuffer(self.defaultFramebufferObject())
		self.fb_ident = ctx.simple_framebuffer((w,h), components=3, dtype='f1')
		self.targets = [ ('screen', self.fb_screen, self.setup_screen), 
						 ('ident', self.fb_ident, self.setup_ident)]
		self.map_ident = np.empty((h,w), dtype='u2')
		self.map_depth = np.empty((h,w), dtype='f4')
		
	def refreshmaps(self):
		''' load the rendered frames from the GPU to the CPU 
			
			- When a picture is used to GPU rendering it's called 'frame'
			- When it is dumped to the RAM we call it 'map' in this library
		'''
		if 'fb_ident' not in self.fresh:
			with self.scene.ctx as ctx:
				ctx.finish()
				self.makeCurrent()	# set the scene context as current opengl context
				self.fb_ident.read_into(self.map_ident, viewport=self.fb_ident.viewport, components=2)
				self.fb_ident.read_into(self.map_depth, viewport=self.fb_ident.viewport, components=1, attachment=-1, dtype='f4')
			self.fresh.add('fb_ident')
			#from PIL import Image
			#Image.fromarray(self.map_ident*16, 'I;16').show()
	
	def render(self):
		# set the opengl current context from Qt (doing it only from moderngl interferes with Qt)
		self.makeCurrent()
		
		# prepare the view uniforms
		s = self.size()
		w, h = s.width(), s.height()
		self.uniforms['view'] = view = self.navigation.matrix()
		self.uniforms['proj'] = proj = self.projection.matrix(w/h, self.navigation.distance)
		self.uniforms['projview'] = proj * view
		self.fresh.clear()
		
		# call the render stack
		self.scene.render(self)
	
	def identstep(self, nidents):
		s = self.step
		self.step += nidents
		self.steps[self.stepi] = self.step-1
		self.stepi += 1
		return s
		
	def setup_ident(self):
		# steps for fast fast search of displays with the idents
		self.stepi = 0
		self.step = 1
		if 'ident' in self.scene.stacks and len(self.scene.stacks['ident']) != len(self.steps):
			self.steps = [0] * len(self.scene.stacks['ident'])
		# ident rendering setup
		ctx = self.scene.ctx
		ctx.multisample = False
		ctx.enable_only(mgl.DEPTH_TEST)
		ctx.blend_func = mgl.ONE, mgl.ZERO
		ctx.blend_equation = mgl.FUNC_ADD
		self.target.clear(0)
	
	def setup_screen(self):
		# screen rendering setup
		ctx = self.scene.ctx
		ctx.multisample = True
		ctx.enable_only(mgl.BLEND | mgl.DEPTH_TEST)
		ctx.blend_func = mgl.SRC_ALPHA, mgl.ONE_MINUS_SRC_ALPHA
		ctx.blend_equation = mgl.FUNC_ADD
		self.target.clear(*settings.display['background_color'])
		
	def preload(self):
		''' internal method to load common ressources '''
		ctx, ressources = self.scene.ctx, self.scene.ressources
		ressources['shader_ident'] = ctx.program(
					vertex_shader=open(ressourcedir+'/shaders/object-ident.vert').read(),
					fragment_shader=open(ressourcedir+'/shaders/ident.frag').read(),
					)

		ressources['shader_subident'] = ctx.program(
					vertex_shader=open(ressourcedir+'/shaders/object-item-ident.vert').read(),
					fragment_shader=open(ressourcedir+'/shaders/ident.frag').read(),
					)

		
	# -- methods to deal with the view --
	
	def somenear(self, point: QPoint, radius=None) -> QPoint:
		''' return the closest coordinate to coords, (within the given radius) for which there is an object at
			So if objnear is returing something, objat and ptat will return something at the returned point
		'''
		if radius is None:	
			radius = settings.controls['snap_dist']
		self.refreshmaps()
		for x,y in snailaround((point.x(), point.y()), (self.map_ident.shape[1], self.map_ident.shape[0]), radius):
			ident = int(self.map_ident[-y, x])
			if ident:
				return QPoint(x,y)
	
	def ptat(self, point: QPoint) -> vec3:
		''' return the point of the rendered surfaces that match the given window coordinates '''
		self.refreshmaps()
		viewport = self.fb_ident.viewport
		depthred = float(self.map_depth[-point.y(),point.x()])
		x =  (point.x()/viewport[2] *2 -1)
		y = -(point.y()/viewport[3] *2 -1)
		
		if depthred == 1.0:
			return None
		else:
			view = self.uniforms['view']
			proj = self.uniforms['proj']
			a,b = proj[2][2], proj[3][2]
			depth = b/(depthred + a) * 0.53	# TODO get the true depth  (can't get why there is a strange factor ... opengl trick)
			#near, far = self.projection.limits  or settings.display['view_limits']
			#depth = 2 * near / (far + near - depthred * (far - near))
			#print('depth', depth, depthred)
			return vec3(fvec3(affineInverse(view) * fvec4(
						depth * x /proj[0][0],
						depth * y /proj[1][1],
						-depth,
						1)))
	
	def ptfrom(self, point: QPoint, center: vec3) -> vec3:
		''' 3D point below the cursor in the plane orthogonal to the sight, with center as origin '''
		view = self.uniforms['view']
		proj = self.uniforms['proj']
		viewport = self.fb_ident.viewport
		x =  (point.x()/viewport[2] *2 -1)
		y = -(point.y()/viewport[3] *2 -1)
		depth = (view * fvec4(fvec3(center),1))[2]
		return vec3(fvec3(affineInverse(view) * fvec4(
					-depth * x /proj[0][0],
					-depth * y /proj[1][1],
					depth,
					1)))
	
	def itemat(self, point: QPoint) -> 'key':
		''' return the key path of the object at the given screen position (widget relative). 
			If no object is at this exact location, None is returned  
		'''
		self.refreshmaps()
		ident = int(self.map_ident[-point.y(), point.x()])
		if ident:
			rdri = bisect(self.steps, ident)
			if rdri == len(self.steps):
				print('internal error: object ident points out of idents list')
			while rdri > 0 and self.steps[rdri-1] == ident:	rdri -= 1
			if rdri > 0:	subi = ident - self.steps[rdri-1] - 1
			else:			subi = ident - 1
			return (*self.scene.stacks['ident'][rdri][0], subi)
			
	# -- view stuff --
	
	def look(self, position: fvec3=None):
		''' Make the scene manipulator look at the position.
			This is changing the camera direction.
		'''
		if not position:	position = self.scene.box().center
		
		if isinstance(self.manipulator, Turntable):
			dir = position - self.manipulator.center
			self.manipulator.yaw = atan(dir.y, dir.x)
			self.manipulator.pitch = atan(dir.z, length(dir.xy))
		elif isinstance(self.manipulator, Orbit):
			dir = position - self.manipulator.center
			focal = self.orient * fvec3(0,0,1)
			self.manipulator.orient = quat(dir, focal) * self.manipulator.orient
		else:
			raise TypeError('manipulator {} is not supported'.format(type(self.manipulator)))
		self.update()
	
	def adjust(self, box:Box=None):
		''' Make the manipulator camera large enough to get the given box in .
			This is changing the zoom level
		'''
		if not box:	box = self.scene.box()
		# get the most distant point to the focal axis
		view = self.navigation.matrix()
		camera, look = fvec3(view[3]), fvec3(view[2])
		dist = length(noproject(box.center-camera, look)) + length(box.width)/2
		# adjust navigation distance
		if isinstance(self.projection, Perspective):
			self.navigation.distance = dist / tan(self.projection.fov/2)
		elif isinstance(self.projection, Orthographic):
			self.navigation.distance = dist
		else:
			raise TypeError('projection {} not supported'.format(type(self.projection)))
	
	def center(self, center: fvec3=None):
		''' Relocate the manipulator to the given position .
			This is translating the camera.
		'''
		if not center:	center = self.scene.box().center
		
		self.navigation.center = center
		self.update()
		
	# -- event system --
	
	def event(self, evt):
		''' Qt event handler
			In addition to the usual subhandlers, inputEvent is called first to handle every InputEvent.
			
			The usual subhandlers are used to implement the navigation through the scene (that is considered to be intrinsic to the scene widget).
		'''
		if isinstance(evt, QInputEvent):
			evt.ignore()
			self.inputEvent(evt)
			if evt.isAccepted():	return True
		return super().event(evt)
	
	def inputEvent(self, evt):
		''' Default handler for every input event (mouse move, press, release, keyboard, ...) 
			When the event is not accepted, the usual matching Qt handlers are used (mousePressEvent, KeyPressEvent, etc).
			
			This function can be overwritten to change the view widget behavior.
		'''
		# set the opengl current context from Qt (doing it only from moderngl interferes with Qt)
		self.makeCurrent()
		
		# send the event to the current tools using the view
		if self.tool:	
			for tool in reversed(self.tool):
				tool(evt)
				if evt.isAccepted():	return
				
		# send the event to the scene objects, descending the item tree
		if isinstance(evt, QMouseEvent) and evt.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
			pos = self.somenear(evt.pos())
			if pos:
				key = self.itemat(pos)
				self.control(key, evt)
				if evt.isAccepted():	return
				
	def control(self, key, evt):
		''' transmit a control event successively to all the displays matching the key path stages.
			At each level, if the event is not accepted, it transmits to sub items
			
			This function can be overwritten to change the interaction with the scene objects.
		'''
		disp = self.scene.displays
		for i in range(1,len(key)):
			disp = disp[key[i-1]]
			disp.control(self, key[:i], key[i:], evt)
			if evt.isAccepted(): return
		
		if evt.type() == QEvent.MouseButtonRelease and evt.button() == Qt.LeftButton:
			disp = self.scene.item(key)
			disp.selected = not disp.selected
			if type(disp).__name__ in ('SolidDisplay', 'WebDisplay'):
				disp.vertices.flags[key[-1]] ^= 0x1
				disp.vertices.vb_flags.write(disp.vertices.flags[disp.vertices.idents])
			self.update()
	
	# -- Qt things --
	
	def initializeGL(self):	pass

	def paintGL(self):
		self.scene.ctx = mgl.create_context()
		self.init()
		self.preload()
		self.render()
		self.paintGL = self.render
		
	def resizeEvent(self, evt):
		super().resizeEvent(evt)
		self.init()
		self.update()


def snail(radius):
	''' generator of coordinates snailing around 0,0 '''
	x = 0
	y = 0
	for r in range(radius):
		for x in range(-r,r):		yield (x,-r)
		for y in range(-r,r):		yield (r, y)
		for x in reversed(range(-r,r)):	yield (x, r)
		for y in reversed(range(-r,r)):	yield (-r,y)

def snailaround(pt, box, radius):
	''' generator of coordinates snailing around pt, coordinates that goes out of the box are skipped '''
	cx,cy = pt
	mx,my = box
	for rx,ry in snail(radius):
		x,y = cx+rx, cy+ry
		if 0 <= x and x < mx and 0 <= y and y < my:
			yield x,y


'''
		-- generators helpers --
'''

class Generated(object):
	''' generator that has a returned value '''
	__slots__ = 'generator', 'value'
	def __init__(self, generator):	self.generator = generator
	def __iter__(self):				self.value = yield from self.generator

class Dispatcher(object):
	''' iterable object that holds a generator built by passing self as first argument
		it allows the generator code to dispatch references to self.
		NOTE:  at contrary to current generators, the code before the first yield is called at initialization
	'''
	__slots__ = 'generator', 'value'
	def __init__(self, func=None, *args, **kwargs):
		self.generator = self._run(func, *args, **kwargs)
		next(self.generator)
	def _run(self, func, *args, **kwargs):
		self.value = yield from func(self, *args, **kwargs)
		
	def send(self, value):	return self.generator.send(value)
	def __iter__(self):		return self.generator
	def __next__(self):		return next(self.generator)

class Tool(Dispatcher):
	''' generator wrapping an yielding function, that unregisters from view.tool once the generator is over '''
	def _run(self, func, *args, **kwargs):
		try:	
			self.value = yield from func(self, *args, **kwargs)
		except StopTool:
			pass
		args[0].tool.remove(self)
	
	def __call__(self, evt):
		try:	return self.send(evt)
		except StopIteration:	pass
		
	def stop(self):
		if self.generator:
			try:	self.generator.throw(StopTool())
			except StopTool:	pass
			except StopIteration:	pass
			self.generator = None
	def __del__(self):
		self.stop()
	
class StopTool(Exception):
	''' used to stop a tool execution '''
	pass


# temporary examples
if False:

	def tutu(self, main):
		evt = yield
		gnagna
		scene.tool = self.send
		budu.iterator = self

	Tool(tutu, main)
	