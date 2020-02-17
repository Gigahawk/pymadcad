'''	
	Defines triangular meshes for pymadcad
'''

from copy import deepcopy
from random import random
import numpy as np
from array import array
from mathutils import Box, vec3, vec4, mat3, mat4, quat, mat3_cast, cross, dot, normalize, length, distance, anglebt, NUMPREC
import math
import view
import text

__all__ = ['Mesh', 'Wire', 'edgekey', 'MeshError']

def ondemand(func):
	''' Decorator for ondemand computed members of instances. 
		The class must have a dictionnary member 'computed'. 
		The result of this decorator is a method that stores its result in the ondemand dictionnary and so 
		doesn't recompute it each time asked.
	'''
	attrname = func.__name__
	def wrapped(self):
		if not attrname in self.computed:
			self.computed[attrname] = func(self)
		return self.computed[attrname]
	wrapped.__name__ = func.__name__
	wrapped.__doc__ = func.__doc__
	return wrapped

class MeshError(Exception):	pass

class Mesh:
	''' Triangular mesh, used to represent volumes or surfaces.
		As volumes are represented by their exterior surface, there is no difference between representation of volumes and faces, juste the way we interpret it.
		
		Attributes:
			points		list of vec3 for points
			faces		list of triplets for faces, the triplet is (a,b,c) such that  cross(b-a, c-a) is the normal oriented to the exterior.
			tracks		integer giving the group each face belong to
			groups		custom information for each group
	'''
	
	# --- standard point container methods ---
	
	def __init__(self, points=None, faces=None, tracks=None, groups=None):
		self.points = points or []
		self.faces = faces or []
		self.tracks = tracks or []
		self.groups = groups or []
		self.options = {}
	
	def transform(self, trans):
		''' apply the transform to the points of the mesh'''
		if isinstance(trans, quat):		trans = mat3_cast(trans)
		if isinstance(trans, vec3):		transformer = lambda v: v + trans
		elif isinstance(trans, mat3):	transformer = lambda v: trans * v
		elif isinstance(trans, mat4):	transformer = lambda v: vec3(trans * vec4(v,1))
		elif callable(trans):	pass
		for i in range(len(self.points)):
			self.points[i] = transformer(self.points[i])
			
	def __add__(self, other):
		''' append the faces and points of the other mesh '''
		if isinstance(other, Mesh):		
			c = Mesh(self.points+other.points, [], [], self.groups+other.groups)
			c.faces.extend(self.faces)
			c.tracks.extend(self.tracks)
			lp = len(self.points)
			lt = len(self.groups)
			for face,track in zip(other.faces, other.tracks):
				c.faces.append((face[0]+lp, face[1]+lp, face[2]+lp))
				c.tracks.append(track+lt)
			return c
		else:
			return NotImplemented
	
	def reverse(self):
		''' reverse direction of all faces '''
		self.faces = [(a,c,b)   for a,b,c in self.faces]
		
	# --- mesh optimization ---
	
	def mergedoubles(self, limit=NUMPREC):
		''' merge points below the specified distance, or below the precision '''
		merges = {}
		for j in reversed(range(len(self.points))):
			for i in range(j):
				if distance(self.points[i], self.points[j]) < limit and i not in merges:
					merges[j] = i
					break
		self.mergepoints(merges)
		return merges
	
	def mergepoints(self, merges):
		''' merge points with the merge dictionnary {src index: dst index}
			remaining points are not removed
		'''
		for i,f in enumerate(self.faces):
			self.faces[i] = (
				merges.get(f[0], f[0]),
				merges.get(f[1], f[1]),
				merges.get(f[2], f[2]),
				)
	
	def strippoints(self):
		''' remove points that are used by no faces, return the reindex list '''
		used = [False] * len(self.points)
		for face in self.faces:
			for p in face:
				used[p] = True
		reindex = striplist(self.points, used)
		for i,f in enumerate(self.faces):
			self.faces[i] = (reindex[f[0]], reindex[f[1]], reindex[f[2]])
		return reindex
	
	def stripgroups(self):
		''' remove groups that are used by no faces, return the reindex list '''
		used = [False] * len(self.groups)
		for track in self.tracks:
			used[track] = True
		reindex = striplist(self.groups, used)
		for i,track in enumerate(self.tracks):
			self.tracks[i] = reindex[track]
		return reindex
	
	def isenvelope(self):
		''' return true if the surfaces are a closed envelope '''
		return len(self.outlines_oriented()) == 0
	
	def isvalid(self):
		''' check that the internal data references are good (indices and list lengths) '''
		l = len(self.points)
		for face in self.faces:
			for p in face:
				if p >= l:	return False
		if len(self.faces) != len(self.tracks):	return False
		if max(self.tracks) >= len(self.groups): return False
		return True
	
	def finish(self):
		''' finish and clean the mesh 
			note that this operation can cost as much as other transformation operation
			job done
				- mergedoubles
				- strippoints
				- stripgroups
		'''
		self.mergedoubles()
		self.strippoints()
		self.stripgroups()
		assert self.isvalid()
	
	
	# --- selection methods ---
	
	def usepointat(self, point):
		''' return the index of the first point in the mesh at the location, if none is found, insert it and return the index '''
		i = self.pointat(point)
		if i is None:
			i = len(self.points)
			self.points.append(point)
		return i
	
	def pointat(self, point):
		''' return the index of the first point at the given location, or None '''
		for i,p in enumerate(self.points):
			if distance(p,point) < NUMPREC:	return i
	
	def pointnear(self, point):
		''' return the nearest point the the given location '''
		return min(	range(len(self.points)), 
					lambda i: distance(self.points[i], point))
	
	def outptnear(self, point):
		''' return the closest point to the given point, that belongs to a group outline '''
		outpts = set()
		for edge in self.outlines_oriented():
			outpts += edge
		return min(	range(len(self.points)), 
					lambda i: distance(self.points[i], point) if i in outpts else math.inf)
	
	def groupnear(self, point):
		''' return the id of the group for the nearest surface to the given point '''
		track = None
		best = math.inf
		for i,face in enumerate(self.faces):
			n = self.facenormal(i)
			dist = abs(dot(point - self.points[face[0]], n))
			if dist < best:
				track = self.tracks[i]
		return track
	
	
	# --- extraction methods ---
	
	def box(self):
		''' return the extreme coordinates of the mesh (vec3, vec3) '''
		max = deepcopy(self.points[0])
		min = deepcopy(self.points[0])
		for pt in self.points:
			for i in range(3):
				if   pt[i] < min[i]:	min[i] = pt[i]
				elif pt[i] > max[i]:	max[i] = pt[i]
		return Box(min, max)
	
	def facenormal(self, face):
		if isinstance(face, int):	
			face = self.faces(face)
		p0 = self.points[face[0]]
		e1 = self.points[face[1]] - p0
		e2 = self.points[face[2]] - p0
		return normalize(cross(e1, e2))
	
	def facepoints(self, index):
		f = self.faces[index]
		return self.points[f[0]], self.points[f[1]], self.points[f[2]]
	
	def edges(self, oriented=True):
		edges = set()
		for face in self.faces:
			edges.add(edgekey(face[0], face[1]))
			edges.add(edgekey(face[1], face[2]))
			edges.add(edgekey(face[2], face[0]))
		return edges
	
	def group(self, groups):
		''' return a new mesh linked with this one, containing only the faces belonging to the given groups '''
		if isinstance(groups, set):			pass
		elif hasattr(groups, '__iter__'):	groups = set(groups)
		else:								groups = (groups,)
		faces = []
		tracks = []
		for f,t in zip(self.faces, self.tracks):
			if t in groups:
				faces.append(f)
				tracks.append(t)
		return Mesh(self.points, faces, tracks, self.groups)
	
	def outlines_oriented(self):
		''' return a set of the ORIENTED edges delimiting the surfaces of the mesh '''
		edges = set()
		for face in self.faces:
			for e in ((face[0], face[1]), (face[1], face[2]), (face[2],face[0])):
				if e in edges:	edges.remove(e)
				else:			edges.add((e[1], e[0]))
		return edges
	
	def outlines_unoriented(self):
		''' return a set of the UNORIENTED edges delimiting the surfaces of the mesh 
			this method is robust to face orientation aberations
		'''
		edges = set()
		for face in self.faces:
			for edge in ((face[0],face[1]),(face[1],face[2]),(face[2],face[0])):
				e = edgekey(*edge)
				if e in edges:	edges.remove(e)
				else:			edges.add(e)
		return edges
	
	outlines = outlines_oriented
	
	
	# --- renderable interfaces ---
		
	def display_triangles(self, scene):		
		if self.options.get('debug_points', False):
			for i,p in enumerate(self.points):
				scene.objs.append(text.Text(
					tuple(p*1.08 + vec3(0,0,0.05*random())), 
					str(i), 
					size=9, 
					color=(0.2, 0.8, 1),
					align=('center', 'center'),
					))
		
		if self.options.get('debug_faces', None) == 'indices':
			for i,f in enumerate(self.faces):
				p = 1.1 * (self.points[f[0]] + self.points[f[1]] + self.points[f[2]]) /3
				scene.objs.append(text.Text(p, str(i), 9, (1, 0.2, 0), align=('center', 'center')))
		if self.options.get('debug_faces', None) == 'tracks':
			for i,f in enumerate(self.faces):
				p = 1.1 * (self.points[f[0]] + self.points[f[1]] + self.points[f[2]]) /3
				scene.objs.append(text.Text(p, str(self.tracks[i]), 9, (1, 0.2, 0), align=('center', 'center')))
		
		fn = np.array([tuple(self.facenormal(f)) for f in self.faces])
		points = np.array([tuple(p) for p in self.points], dtype=np.float32)		
		lines = []
		for i in range(0, 3*len(self.faces), 3):
			lines.append((i, i+1))
			lines.append((i+1, i+2))
			lines.append((i, i+2))
		
		idents = []
		for i in self.tracks:
			idents.append(i)
			idents.append(i)
			idents.append(i)
		
		scene.objs.append(view.SolidDisplay(scene,
			points[np.array(self.faces, dtype='u4')].reshape((len(self.faces)*3,3)),
			np.hstack((fn, fn, fn)).reshape((len(self.faces)*3,3)),
			faces = np.array(range(3*len(self.faces)), dtype='u4').reshape(len(self.faces),3),
			idents = np.array(idents, dtype='u2'),
			lines = np.array(lines, dtype='u4'),
			))
	
	def display_groups(self, scene):
		facenormals = [self.facenormal(f)  for f in self.faces]
		# buffers for display
		points = array('f')
		normals = array('f')
		usage = array('f')
		faces = array('L')
		edges = array('L')
		tracks = array('H')
		# function to register new points
		def usept(pi,xi,yi, fi, used):
			o = self.points[pi]
			x = self.points[xi] - o
			y = self.points[yi] - o
			contrib = anglebt(x,y)
			if pi in used:
				i = used[pi]
				# contribute to the points normals
				usage[i] += contrib
				normals[3*i+0] += facenormals[fi][0] * contrib
				normals[3*i+1] += facenormals[fi][1] * contrib
				normals[3*i+2] += facenormals[fi][2] * contrib
				return i
			else:
				points.append(self.points[pi][0])
				points.append(self.points[pi][1])
				points.append(self.points[pi][2])
				normals.append(facenormals[fi][0] * contrib)
				normals.append(facenormals[fi][1] * contrib)
				normals.append(facenormals[fi][2] * contrib)
				usage.append(contrib)
				tracks.append(self.tracks[fi])
				j = used[pi] = len(points) // 3 -1
				return j
		
		# get the faces for each group
		for group in range(len(self.groups)):
			# reset the points extraction for each group
			indices = {}
			frontier = set()
			# get faces and exterior edges
			for i,face in enumerate(self.faces):
				if self.tracks[i] == group and face[0] != face[1] and face[1] != face[2] and face[2] != face[0]:
					faces.append(usept(face[0],face[1],face[2], i, indices))
					faces.append(usept(face[1],face[2],face[0], i, indices))
					faces.append(usept(face[2],face[0],face[1], i, indices))
					for edge in ((face[0], face[1]), (face[1], face[2]), (face[2],face[0])):
						e = edgekey(*edge)
						if e in frontier:	frontier.remove(e)
						else:				frontier.add(e)
			# render exterior edges
			for edge in frontier:
				edges.append(indices[edge[0]])
				edges.append(indices[edge[1]])
		
		for i,u in enumerate(usage):
			normals[3*i+0] /= u
			normals[3*i+1] /= u
			normals[3*i+2] /= u
		
		scene.objs.append(view.SolidDisplay(scene,
			np.array(points).reshape((len(points)//3,3)),
			np.array(normals).reshape((len(normals)//3,3)),
			faces = np.array(faces).reshape((len(faces)//3,3)),
			lines = np.array(edges).reshape((len(edges)//2,2)),
			idents = np.array(tracks, dtype=view.IDENT_TYPE),
			color = self.options.get('color', None),
			))
	
	def display(self, scene):
		if self.options.get('debug_display', False):
			self.display_triangles(scene)
		else:
			self.display_groups(scene)
	
	def __repr__(self):
		return 'Mesh(\n  points= {},\n  faces=  {},\n  tracks= {},\n  groups= {},\n  options= {})'.format(
					reprarray(self.points, 'points'),
					reprarray(self.faces, 'faces'),
					reprarray(self.tracks, 'tracks'),
					reprarray(self.groups, 'groups'),
					repr(self.options))
		

def reprarray(array, name):
	if len(array) <= 5:		content = ', '.join((str(e) for e in array))
	elif len(array) <= 20:	content = ',\n           '.join((str(e) for e in array))
	else:					content = '{} {}'.format(len(array), name)
	return '['+content+']'

def striplist(list, used):
	''' remove all elements of list that match a False in used, return a reindexation list '''
	reindex = [0] * len(list)
	j = 0
	for i,u in enumerate(used):
		if u:
			list[j] = list[i]
			reindex[i] = j
			j += 1
	list[j:] = []
	return reindex


def edgekey(a,b):
	''' return a key for a non-directional edge '''
	if a < b:	return (a,b)
	else:		return (b,a)
	


class Wire:
	''' Hold datas for creation of surfaces from outlines
		the wire holds segments, formed by couple of points, tracks associates group number to each segment
	'''
	def __init__(self, points, lines, tracks, groups):
		self.points = points
		self.lines = lines
		self.tracks = tracks or [0] * len(self.lines)
		self.groups = groups or [None] * (max(self.tracks)+1)
		
	def transform(self, trans):
		''' apply the transform to the points of the mesh'''
		if isinstance(trans, quat):		trans = mat3_cast(trans)
		if isinstance(trans, vec3):		transformer = lambda v: v + trans
		elif isinstance(trans, mat3):	transformer = lambda v: trans * v
		elif isinstance(trans, mat4):	transformer = lambda v: vec3(trans * vec4(v,1))
		elif callable(trans):	pass
		for i in range(len(self.points)):
			self.points[i] = transformer(self.points[i])
	
	def mergepoints(self):
		for i,e in enumerate(self.lines):
			self.lines[i] = (
				merges.get(e[0], e[0]),
				merges.get(e[1], e[1]),	
				)
	
	def strippoints(self):
		used = [False] * len(self.points)
		for edge in self.lines:
			for p in edge:
				used[p] = True
		reindex = striplist(self.points, used)
		for i,e in enumerate(self.lines):
			self.lines[i] = (reindex[e[0]], reindex[e[1]])
		return reindex
		
	def stripgroups(self):
		used = [False] * len(self.groups)
		for track in self.tracks:
			used[track] = True
		reindex = striplist(self.groups, used)
		for i,track in enumerate(self.tracks):
			self.tracks[i] = reindex[track]
		return reindex
	