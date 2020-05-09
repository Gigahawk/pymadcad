''' Regroupement des fonctions et classes math de pymadcad '''

import glm
from glm import *
del version, license
from math import pi, atan2
from copy import deepcopy
max = __builtins__['max']
min = __builtins__['min']
any = __builtins__['any']
all = __builtins__['all']


vec2 = dvec2
mat2 = dmat2
vec3 = dvec3
mat3 = dmat3
vec4 = dvec4
mat4 = dmat4
quat = dquat

NUMPREC = 1e-13
COMPREC = 1-NUMPREC

# numerical precision of floats used (float32 here, so 7 decimals, so 1e-6 when exponent is 1)
#NUMPREC = 1e-6
#COMPREC = 1-NUMPREC

def norminf(x):
	return max(glm.abs(x))

def norm1(x):
	return sum(glm.abs(x))

norm2 = length

def anglebt(x,y):
	n = length(x)*length(y)
	return acos(min(1,max(-1, dot(x,y)/n)))	if n else 0

def project(vec, dir):
	return dot(vec, dir) * dir
	
def noproject(x,dir):	
	return x - project(x,dir)

def perpdot(a:vec2, b:vec2) -> float:
	return -a[1]*b[0] + a[0]*b[1]

def perp(v:vec2) -> vec2:
	return vec2(-v[1], v[0])
	
def dirbase(dir, align=vec3(1,0,0)):
	''' returns a base using the given direction as z axis (and the nearer vector to align as x) '''
	x = align - project(align, dir)
	if length(x) < NUMPREC:
		align = vec3(align[2],-align[0],align[1])
		x = align - project(align, dir)
	x = normalize(x)
	y = cross(dir, x)
	return x,y,dir

def scaledir(dir, factor):
	''' return a mat3 scaling in the given direction, with the given factor (1 means original scale) '''
	return mat3(1) + (factor-1)*mat3(dir[0]*dir, dir[1]*dir, dir[2]*dir)

def transform(*args):
	''' create an affine transformation matrix
		supported inputs:
			mat4
			vec3                                    - translation only
			quat, mat3, mat4                        - rotation only
			(vec3,vec3), (vec3,mat3), (vec3,quat)   - translation and rotation
			(vec3,vec3,vec3)                        - base of vectors for rotation
			(vec3,vec3,vec3,vec3)                   - translation and base of vectors for rotation
	'''
	if len(args) == 1 and isinstance(args[0], tuple):
		args = args[0]
	if len(args) == 1:
		if isinstance(args[0], mat4):	return args[0]
		elif isinstance(args[0], mat3):	return mat4(args[0])
		elif isinstance(args[0], quat):	return mat4_cast(args[0])
		elif isinstance(args[0], vec3):	return translate(mat4(1), args[0])
	elif len(args) == 2:
		if isinstance(args[0], vec3):
			if   isinstance(args[1], mat3):		m = args[1]
			elif isinstance(args[1], quat):		m = mat4_cast(args[1])
			elif isinstance(args[1], vec3):		m = mat4_cast(quat(args[1]))
			m[3] = vec4(args[0], 1)
			return m
	elif isinstance(args[0], vec3) and len(args) == 3:			
		return mat4(mat3(*args))
	elif isinstance(args[0], vec3) and len(args) == 4:			
		m = mat4(mat3(args[1:]))
		m[3] = vec4(args[0], 1)
		return m
	
	raise TypeError('a transformation must be a  mat3, mat4, quat, (O,mat3), (O,quat), (0,x,y,z)')


def interpol1(a, b, x):
	''' 1st order polynomial interpolation '''
	return (1-x)*a + x*b

def interpol2(a, b, x):
	''' 3rd order polynomial interpolation 
		a and b are iterable of successive derivatives of a[0] and b[0]
	'''
	return (	2*x*(1-x)  * interpol1(a[0],b[0],x)		# linear component
			+	x**2       * (b[0] + (1-x)*b[1])		# tangent
			+	(1-x)**2   * (a[0] + x*a[1])	# tangent
			)

spline = interpol2


def dichotomy_index(l, index, key=lambda x:x):
	''' use dichotomy to get the index of `index` in a list sorted in ascending order
		key can be used to specify a function that gives numerical value for list elements
	'''
	start,end = 0, len(l)
	while start < end:
		mid = (start+end)//2
		val = key(l[mid])
		if val < index:		start =	mid+1
		elif val > index:	end =	mid
		else:	return mid
	return start



class Box:
	__slots__ = ('min', 'max')
	def __init__(self, min=None, max=None, center=vec3(0), width=vec3(0)):
		if min and max:			self.min, self.max = min, max
		else:					self.min, self.max = center-width, center+width
	
	@property
	def center(self):
		return (self.min + self.max) /2
	@property
	def width(self):
		return self.max - self.min
	
	def __add__(self, other):
		if isinstance(other, vec3):		return Box(self.min + other, self.max + other)
		elif isinstance(other, Box):	return Box(other.min, other.max)
		else:
			return NotImplemented
	def __iadd__(self, other):
		if isinstance(other, vec3):		
			self.min += other
			self.max += other
		elif isinstance(other, Box):	
			self.min += other.min
			self.max += other.max
		else:
			return NotImplemented
	def __sub__(self, other):
		if isinstance(other, vec3):		return Box(self.min - other, self.max - other)
		elif isinstance(other, Box):	return Box(other.min, other.max)
		else:
			return NotImplemented
	def __or__(self, other):	return deepcopy(self).union(other)
	def __and__(self, other):	return deepcopy(self).intersection(other)
	def union(self, other):
		if isinstance(other, vec3):
			self.min = glm.min(self.min, other)
			self.max = glm.max(self.max, other)
		elif isinstance(other, Box):
			self.min = glm.min(self.min, other.min)
			self.max = glm.max(self.max, other.max)
		else:
			return NotImplemented
		return self
	def intersection(self, other):
		if isinstance(other, vec3):
			self.min = glm.max(self.min, other)
			self.max = glm.min(self.max, other)
		elif isinstance(other, Box):
			self.min = glm.max(self.min, other.min)
			self.max = glm.min(self.max, other.max)
		else:
			return NotImplemented
		for i in range(3):
			if self.min[i] > self.max[i]:
				self.min[i] = self.max[i] = (self.min[i]+self.max[i])/2
				break
		return self
	def __bool__(self):
		for i in range(3):
			if self.min[i] >= self.max[i]:	return False
		return True