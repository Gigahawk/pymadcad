from copy import deepcopy
from mathutils import vec3, ivec3, noproject, norminf, ceil, normalize, length, dot, glm, cross
from mesh import Web
from functools import reduce
from math import nan, inf, floor, ceil

class PositionMap:
	''' Holds objects assoiated with their location
		every object can be bound to multiple locations, and each location can hold multiple objects
		cellsize defines the box size for location hashing (the smaller it is, the bigger the memory footprint will be for non-point primitives)
		
		Attributes defined here:
			cellsize   - the boxing parameter (DON'T CHANGE IT IF NON-EMPTY)
			dict       - the hashmap from box to objects lists
	'''
	__slots__ = 'cellsize', 'dict'
	def __init__(self, cellsize, iterable=None):
		self.cellsize = cellsize
		self.dict = {}
		if iterable:	self.update(iterable)
	'''
	def keysfor(self, space):
		cell = self.cellsize
		# point
		if isinstance(space, vec3):
			yield tuple(ivec3(pt/cell))
		# segment
		elif isinstance(space, tuple) and len(space) == 2:
			p = deepcopy(space[0])
			v = space[1]-space[0]
			l = length(v)
			v /= l
			yield tuple(ivec3(p/cell))
			while dot(p-space[0],v) < l:
				prox = [(cell - p[i]%cell)/v[i] if v[i] else 0		for i in range(3)]
				i = 0
				if prox[1] < prox[i]:	i=1
				if prox[1] < prox[i]:	i=2
				p += v*prox[i]
				yield tuple(ivec3(p/cell))
		# triangle
		elif isinstance(space, tuple) and len(space) == 3:
			indev
		else:
			raise TypeError("PositionMap only supports keys of type:  points, segments, triangles")
	'''
	
	def keysfor(self, space):
		''' rasterize the primitive, yielding the successive position keys '''
		cell = self.cellsize
		# point
		if isinstance(space, vec3):
			yield tuple(ivec3(space/cell))
		# segment
		elif isinstance(space, tuple) and len(space) == 2:
			
			p = deepcopy(space[0])
			v = normalize(space[1]-space[0])
			yield tuple(ivec3(p/cell))
			while dot(space[1]-p,v) >= 0:
				#prox = [(cell - p[i]%cell)/v[i] if v[i] else 0		for i in range(3)]
				prox = glm.abs((cell - p%cell)/v)
				i = 0
				if prox[1] < prox[i]:	i=1
				if prox[1] < prox[i]:	i=2
				a = v*prox[i]
				yield tuple(ivec3((p+a/2)/cell))
				p += a
			'''
			keys = set()
			p = deepcopy(space[0])
			v = space[1]-p
			n = int(ceil(norminf(v/cell)))
			v /= n
			keys.add(tuple(ivec3((p-v)/cell)))
			for i in range(n):
				p += v
				keys.add(tuple(ivec3(p/cell)))
			yield from keys
			'''
		# triangle
		elif isinstance(space, tuple) and len(space) == 3:
			'''
			keys = set()
			pa = deepcopy(space[0])
			pb = deepcopy(space[0])
			n = int(ceil(min(
					norminf(space[0]-space[1]),
					norminf(space[1]-space[2]),
					norminf(space[2]-space[0]),
					)/ cell)) * 2
			va = (space[1]-pa)/n
			vb = (space[2]-pb)/n
			keys.add(tuple(ivec3(pa/cell)))
			for i in range(n):
				pa += va
				pb += vb
				keys.update(self.keysfor((pa, pb)))
				#yield tuple(ivec3(pa/cell))
				#yield tuple(ivec3(pb/cell))
			yield from keys
			'''
			# permutation of coordinates to get the normal the closer to Z
			n = glm.abs(cross(space[1]-space[0], space[2]-space[0]))
			if n[1] >= n[0] and n[1] >= n[2]:	order = (2,0,1)
			elif n[0] >= n[1] and n[0] >= n[2]:	order = (1,2,0)
			else:								order = (0,1,2)
			space = [ vec3(p[order[0]], p[order[1]], p[order[2]])	for p in space]
			
			# prepare variables
			v = [space[i-1]-space[i]	for i in range(3)]
			n = cross(v[0],v[1])
			dx = -n[0]/n[2]
			dy = -n[1]/n[2]
			o = space[0]
			cell2 = cell/2
			pmin = reduce(glm.min, space)
			pmax = reduce(glm.max, space)
			
			# x selection
			xmin,xmax = pmin[0],pmax[0]
			xmin -= xmin%cell
			xpts = [xmin+cell*i+cell2	for i in range(max(1,ceil((xmax-xmin)/cell)))]
			
			# y selection
			ypts = []
			for x in xpts:
				cand = []
				for i in range(3):
					if (space[i-1][0]-x+cell2)*(space[i][0]-x-cell2) <= 0 or (space[i-1][0]-x-cell2)*(space[i][0]-x+cell2) <= 0:	# NOTE: cet interval ajoute parfois des cases inutiles apres les sommets
						cand.append( space[i][1] + v[i][1]/(v[i][0] if v[i][0] else inf) * (x-cell2-space[i][0]) )
						cand.append( space[i][1] + v[i][1]/(v[i][0] if v[i][0] else inf) * (x+cell2-space[i][0]) )
				ymin,ymax = min(cand), max(cand)
				ymin -= ymin%cell
				ypts.extend(( (x,ymin+cell*i+cell2)	for i in range(max(1,ceil((ymax-ymin)/cell))) ))
				
			# z selection
			zpts = []
			for x,y in ypts:
				f = lambda x,y:	o[2] + dx*(x-o[0]) + dy*(y-o[1])
				cand = []
				cand.append( f(x-cell2, y-cell2) )
				cand.append( f(x+cell2, y-cell2) )
				cand.append( f(x-cell2, y+cell2) )
				cand.append( f(x+cell2, y+cell2) )
				zmin,zmax = min(cand), max(cand)
				zmin -= zmin%cell
				zpts.extend(( (x,y,zmin+cell*i+cell2)	for i in range(max(1,ceil((zmax-zmin)/cell))) ))
			
			# remove box from corners that goes out of the area
			pmin -= pmin%cell
			pmax += cell - pmax%cell
			for p in zpts:
				if pmin[0]<p[0] and pmin[1]<p[1] and pmin[2]<p[2] and p[0]<pmax[0] and p[1]<pmax[1] and p[2]<pmax[2]:
					yield tuple([floor(p[order[i]]/cell)	for i in range(3)])
		else:
			raise TypeError("PositionMap only supports keys of type:  points, segments, triangles")
	
	def update(self, other):
		if isinstance(other, PositionMap):
			assert self.cellsize == other.cellsize
			for k,v in other.dict.items():
				if k in self.dict:	self.dict[k].extend(v)
				else:				self.dict[k] = v
		elif hasattr(other, '__iter__'):
			for space,obj in other:
				self.add(space,obj)
		else:
			raise TypeError("update requires a PositionMap or an iterable of couples (space, obj)")
	
	def add(self, space, obj):
		for k in self.keysfor(space):
			if k not in self.dict:	self.dict[k] = [obj]
			else:					self.dict[k].append(obj)
	
	def get(self, space):
		for k in self.keysfor(space):
			if k in self.dict:
				yield from self.dict[k]
	
	_display = Web(
		[	
			vec3(0,0,0),
			vec3(1,0,0),vec3(0,1,0),vec3(0,0,1),
			vec3(0,1,1),vec3(1,0,1),vec3(1,1,0),
			vec3(1,1,1)],
		[	
			(0,1),(0,2),(0,3),
			(1,6),(2,6),
			(1,5),(3,5),
			(2,4),(3,4),
			(4,7),(5,7),(6,7),
			],
		)
	def display(self, scene):
		web = Web()
		base = vec3(self.cellsize)
		for k in self.dict:
			l = len(web.points)
			web += Web([base*(p+k)  for p in self._display.points], self._display.edges, groups=[k])
		return web.display(scene)



class PointSet:
	''' Holds a list of points and hash them.
		the points are holds using indices, that allows to get the point buffer at any time, or to retreive only a point index
		cellsize defines the box size in which two points are considered to be the same
		
		methods are inspired from the builtin type set
		
		Attributes defined here:
			points     - the point buffer (READ-ONLY PURPOSE)
			cellsize   - the boxing parameter (DON'T CHANGE IT IF NON-EMPTY)
			dict       - the hashmap from box to point indices
	'''
	__slots__ = 'points', 'cellsize', 'dict'
	def __init__(self, cellsize, iterable=None):
		self.points = []
		self.dict = {}
		if iterable:	self.update(iterable)
	
	def keyfor(self, pt):
		return tuple(ivec3(pt/self.cellsize))
	
	def update(self, iterable):
		for pt in iterable:	self.add(pt)
	def difference_update(self, iterable):
		for pt in iterable:	self.discard(pt)
		
	def add(self, pt):
		key = self.keyfor(pt)
		if key not in self.dict:
			self.dict[key] = len(self.points)
			self.points.append(pt)
	def remove(self, pt):
		key = self.keyfor(p)
		if key in self.dict:	del self.dict[k]
		else:					raise IndexError("position doesn't exist in set")
	def discard(self, pt):
		key = self.keyfor(p)
		if key in self.dict:	del self.dict[k]
	
	def __contains__(self, pt):
		return self.keyfor(p) in self.dict
	def __getitem__(self, pt):
		key = self.keyfor(pt)
		if key in self.dict:	return self.dict[key]
		else:					raise IndexError("position doesn't exist in set")
		
	__iadd__ = update
	__isub__ = difference_update
	def __add__(self, iterable):
		s = PositionSet()
		s.union(self.points)
		s.union(iterable)
		return s
	def __sub__(self, iterable):
		s = PositionSet()
		s.union(self.points)
		s.difference(iterable)
		return s


if __name__ == '__main__':
	from mesh import Mesh
	
	triangles = Mesh([
						vec3(1,1,0), vec3(3,1,0), vec3(1,3,0),
						vec3(0,1,1), vec3(0,3,1), vec3(0,1,3),
						vec3(1,0,1), vec3(3,0,1), vec3(1,0,3),
						vec3(1,2,5), vec3(-3,0,4), vec3(4,-2,7),
						],
					[(0,1,2), (3,4,5), (6,7,8), (9,10,11)],
					)
	m = PositionMap(0.7, [
		(triangles.facepoints(0), 'x'),
		(triangles.facepoints(1), 'y'),
		(triangles.facepoints(2), 'z'),
		(triangles.facepoints(3), 'truc'),
		])
	
	from mathutils import Box,fvec3
	import view
	import sys
	from PyQt5.QtWidgets import QApplication
	app = QApplication(sys.argv)
	scn = view.Scene()
	scn.add(m)
	scn.add(triangles)
	scn.look(Box(center=fvec3(0,0,3), width=fvec3(4)))
	scn.show()
	sys.exit(app.exec())