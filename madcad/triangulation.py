from math import inf
from .mathutils import glm,vec2,dvec2,dmat2, perp, perpdot, length, distance, normalize, inverse, isnan, norminf, NUMPREC
from .mesh import Mesh, Web, Wire, MeshError


def triangulation(outline, prec=NUMPREC):
	try:				m = triangulation_outline(outline, prec)
	except MeshError:	m = triangulation_skeleton(outline, prec)
	return m


def skeleting(outline: Wire, skeleting: callable, prec=NUMPREC) -> [vec2]:
	''' skeleting procedure for the given wire
		at each step, the skeleting function is called
		created points will be added to the wire point buffer and this buffer is returned (ROI)
	'''
	l = len(outline)
	pts = outline.points
	
	# edge normals
	enormals = [perp(normalize(outline[i]-outline[i-1]))	for i in range(l)]
	# compute half axis starting from each point
	haxis = []
	for i in range(l):
		haxis.append((outline.indices[i], i, (i+1)%l))
	
	# create the intersections to update
	intersect = [(0,0)] * l	# intersection for each edge
	dist = [-1] * l	# min distance for each edge
	def eval_intersect(i):
		o1,a1,b1 = haxis[i-1]
		o2,a2,b2 = haxis[i]
		# compute normals to points
		v1 = enormals[a1]+enormals[b1]
		v2 = enormals[a2]+enormals[b2]
		if norminf(v1) < prec:	v1 =  perp(enormals[b1])	# if edges are parallel, take the direction to the shape
		if norminf(v2) < prec:	v2 = -perp(enormals[b2])
		# compute the intersection
		x1,x2 = inverse(dmat2(v1,-v2)) * dvec2(-pts[o1] + pts[o2])
		if x1 >= -NUMPREC and x2 >= -NUMPREC:
			intersect[i] = pts[o2] + x2*v2
			dist[i] = min(x1*length(v1), x2*length(v2))
		elif isnan(x1) or isnan(x2):
			intersect[i] = pts[o2]
			dist[i] = 0
		else:
			intersect[i] = None
			dist[i] = inf
	for i in range(l):
		eval_intersect(i)
	
	# build skeleton
	while len(haxis) > 1:
		print(dist)
		i = min(range(len(haxis)), key=lambda i:dist[i])
		assert dist[i] != inf, "no more intersection found (algorithm failure)"
		o1,a1,b1 = haxis[i-1]
		o2,a2,b2 = haxis[i]
		# add the intersection point
		ip = len(pts)
		pts.append(intersect[i])
		# extend skeleton
		skeleting(haxis, i, ip)
		# create the new half axis
		haxis.pop(i)
		dist.pop(i)
		intersect.pop(i)
		haxis[i-1] = (ip, a1, b2)
		eval_intersect((i-2) % len(haxis))
		eval_intersect((i-1) % len(haxis))
		eval_intersect(i % len(haxis))
		eval_intersect((i+1) % len(haxis))
		eval_intersect((i+2) % len(haxis))
	
	return pts

def skeleton(outline: Wire, prec=NUMPREC) -> Web:
	''' return a Web that constitute the skeleton of the outline
		the returned Web uses the same point buffer than the input Wire.
		created points will be added into it
	'''
	skeleton = []
	#def sk(ip, o1,o2, a1,b1, a2,b2):
		#skeleton.append((o1,ip))
		#skeleton.append((o2,ip))
	def sk(haxis, i, ip):
		skeleton.append((haxis[i-1][0], ip))
		skeleton.append((haxis[i][0], ip))
	pts = skeleting(outline, sk, prec)
	return Web(pts, skeleton)

def triangulation_skeleton(outline: Wire, prec=NUMPREC) -> Mesh:
	''' return a Mesh with triangles filling the surface of the outline 
		the returned Mesh uses the same point buffer than the input Wire
	'''
	triangles = []
	skeleton = []
	pts = outline.points
	original = len(pts)
	minbone = [inf]
	def sk(haxis, i, ip):
		triangles.append((haxis[i-2][0], haxis[i-1][0], ip))
		triangles.append((haxis[i-1][0], haxis[i][0], ip))
		triangles.append((haxis[i][0], haxis[(i+1)%len(haxis)][0], ip))
		if   haxis[i-1][0] < original:
			d = distance(pts[haxis[i-1][0]], pts[ip])
			if d < minbone[0]:	minbone[0] = d
		else:
			skeleton.append((haxis[i-1][0], ip))
		if haxis[i][0] < original:
			d = distance(pts[haxis[i][0]], pts[ip])
			if d < minbone[0]:	minbone[0] = d
		else:
			skeleton.append((haxis[i][0], ip))
	pts = skeleting(outline, sk, prec)
	m = Mesh(pts, triangles)
	# merge points from short internal edges
	minbone = 0.5*minbone[0]
	merges = {}
	for a,b in skeleton:
		if distance(pts[a], pts[b]) < minbone:
			if   a not in merges:	merges[a] = merges.get(b,b)
			elif b not in merges:	merges[b] = merges.get(a,a)
	for k,v in merges.items():
		while v in merges and merges[v] != v:	
			if distance(pts[k], pts[v]) > minbone:
				merges[k] = k
				merges[v] = v
				break
			merges[k] = v = merges[v]
	m.mergepoints(merges)
	return m

def aesthetic(u,v):
	''' appreciation criterion for 2D triangles
		currently it computes     surface / perimeter**2
	'''
	return perpdot(u,v) / (length(u)+length(v)+length(u-v))**2

def triangulation_outline(outline: Wire, normal=None) -> Mesh:
	''' return a mesh with the triangles formed in the outline
		the returned mesh uses the same buffer of points than the input
	'''
	try:				proj = planeproject(outline, normal)
	except ValueError:	return Mesh()
	
	hole = list(outline.indices)
	def score(i):
		l = len(hole)
		u = proj[(i+1)%l] - proj[i]
		v = proj[(i-1)%l] - proj[i]
		sc = aesthetic(u,v)
		if sc < 0:	return sc
		# check that there is not point of the outline inside the triangle
		decomp = inverse(dmat2(u,v))
		o = proj[i]
		triangle = ((i-1)%l, i, (i+1)%l)
		for j in range(l):
			if j not in triangle:
				p = proj[j]
				uc,vc = decomp * dvec2(p-o)
				if 0 <= uc and 0 <= vc and uc+vc <= 1:
					sc = -inf
					break
		return sc
	scores = [score(i) for i in range(len(hole))]
	
	triangles = []
	while len(hole) > 2:
		l = len(hole)
		i = max(range(l), key=lambda i:scores[i])
		#assert scores[i] >= -NUMPREC, "no more feasible triangles (algorithm failure)"
		if scores[i] < -NUMPREC:	print('warning: no more feasible triangles')
		triangles.append((hole[(i-1)%l], hole[i], hole[(i+1)%l]))
		hole.pop(i)
		proj.pop(i)
		scores.pop(i)
		l -= 1
		scores[(i-1)%l] = score((i-1)%l)
		scores[i%l] = score(i%l)
	
	return Mesh(outline.points, triangles)

from .mathutils import dirbase, cross, noproject
def planeproject(pts, normal=None):
	''' project an outline in a plane, to get its points as vec2 '''
	x,y,z = guessbase(pts, normal)
	i = min(range(len(pts)), key=lambda i: dot(pts[i],x))
	l = len(pts.indices)
	if dot(z, cross(pts[(i+1)%l]-pts[i], pts[(i-1)%l]-pts[i])) < 0:
		y = -y
	return [vec2(dot(p,x), dot(p,y))	for p in pts]

def guessbase(pts, normal=None, thres=10*NUMPREC):
	''' build a base in which the points will be in plane XY 
		thres is the precision threshold between axis for point selection
	'''
	if normal:
		return dirbase(normal)
	pts = iter(pts)
	try:
		o = next(pts)
		x = vec3(0)
		y = vec3(0)
		ol = max(glm.abs(o))
		xl = 0
		zl = 0
		while xl < thres:
			p = next(pts)
			x = p-o
			xl = dot(x,x)/max(max(glm.abs(p)), ol)
		x = normalize(x)
		while zl < thres:
			p = next(pts)
			y = p-o
			zl = length(cross(y,x))
		y = normalize(noproject(y,x))
		return x, y, cross(x,y)
	except StopIteration:
		raise ValueError('unable to extract 2 directions')

from .mathutils import dot, vec3, Box
from nprint import nprint

def ivmax(v):
	''' index of maximum coordinate of a vec3 '''
	i = 0
	if v[1] > v[i]:	i = 1
	if v[2] > v[i]:	i = 2
	return i

def ivsort(v):
	''' coordinates sort indices for a vec3 '''
	i = 0
	if v[1] > v[i]:	i = 1
	if v[2] > v[i]:	i = 2
	if v[(i+1)%3] > v[(i-1)%3]:		j,k = (i+1)%3, (i-1)%3
	else:							j,k = (i-1)%3, (i+1)%3
	return (i,j,k)
	

from math import sqrt
	
def sweepline_loops(outline: Web):
	''' sweep line algorithm to retreive loops from a Web
		the web edges should not be oriented, and thus the resulting face has no orientation
		complexity: O(n*ln2(n))
	'''
	if len(outline.edges) < 3:	return Mesh()
	pts = outline.points
	loops = []
	finalized = []
	
	# select the sweepline direction with the maximum interval
	box = Box(center=pts[outline.edges[0][0]])
	for edge in outline.edges:
		for p in edge:
			box.union(pts[p])
	diag = glm.abs(box.width)
	sortdim, ydim, _ = ivsort(diag)
	def affine(e):
		v = pts[e[1]] - pts[e[0]]
		return (pts[e[0]], v/v[sortdim] if v[sortdim] else vec3(0))
	
	# direction of direct rotation of the outline, orthogonal to the sweepline direction
	y = vec3(0)
	y[ydim] = 1
	print('sortdim', sortdim, 'y', ydim)
	def orthoproj(v):
		l = sqrt(v[ydim]**2 + v[sortdim]**2)
		return v[ydim] / l if l else 0
	
	# orient edges along the axis and sort them
	# sorting is done using absciss and orientation in case of similar absciss
	# the nearest directions to +-y is prefered to speedup cluster distinction
	edges = outline.edges[:]
	for i,(a,b) in enumerate(edges):
		if pts[a][sortdim] < pts[b][sortdim]:	edges[i] = b,a
	stack = sorted(edges,
				key=lambda e: (pts[e[0]][sortdim], -abs(orthoproj(pts[e[1]]-pts[e[0]])) )
				)
	# remove absciss ambiguity (for edges that share points with the same absciss)
	# for each edge, all following edges with the same absciss and contains its start point will have the same startpoint
	for i in reversed(range(len(stack))):
		l = stack[i][0]
		n = i-1
		for j in reversed(range(i)):
			if pts[stack[j][0]][sortdim] < pts[l][sortdim]:	break
			if stack[j][1] == l:	
				stack[j] = (stack[j][1], stack[j][0])
			if stack[j][0] == l and n != j:
				stack.insert(n, stack.pop(j))
				n -= 1
	#print('stack', stack)
	print('stack')
	for e in stack:
		print(e, (pts[e[0]][sortdim], orthoproj(pts[e[1]]-pts[e[0]])))
	
	# build cluster by cluster -  each cluster is a monotone sub-polygon
	clusters = []
	while stack:
		edge = stack.pop()
		# get the pair edge if there is one starting at the same point
		m = None
		sc = -1
		i = len(stack)-1
		while i >= 0 and pts[stack[i][0]][sortdim] == pts[edge[0]][sortdim]:
			e = stack[i]
			if e[0] == edge[0]:
				diff = abs(orthoproj(pts[e[1]]-pts[e[0]]) - orthoproj(pts[edge[1]]-pts[edge[0]]))
				if diff > sc:	
					sc = diff
					m = i
			i -= 1
		if m is not None:	
			coedge = stack.pop(m)
			if orthoproj(pts[edge[1]]-pts[edge[0]]) < orthoproj(pts[coedge[1]]-pts[coedge[0]]):
				edge, coedge = coedge, edge
		else:
			coedge = None
				
		print('stack', stack)
		print('*', edge, coedge, pts[edge[0]][sortdim])
		
		# search in which cluster we are
		found = False
		i = 0
		while i < len(clusters):
			p0, p1 = pts[edge[0]], pts[edge[1]]
			l0,l1,a0,a1 = clusters[i]
			
			if l0[1] == l1[1]:
				print('    pop', l0,l1)
				clusters.pop(i)
				loops[i].append(l0[1])
				finalized.append(loops.pop(i))
				continue
			
			print('   ', l0,l1,edge[0])
			# continuation of already existing edge of the cluster
			if edge[0] == l0[1]:
				loops[i].append(l0[1])
				clusters[i] = (edge, l1, affine(edge), a1)
				if coedge:
					stack.append(coedge)
				print('      continuation', edge)
				#if coedge:	nprint(clusters)
				found = True
				break
			elif edge[0] == l1[1]:
				loops[i].insert(0, l1[1])
				clusters[i] = (l0, coedge or edge, a0, affine(coedge or edge))
				if coedge:
					stack.append(edge)
				print('      continuation', coedge or edge)
				#if coedge:	nprint(clusters)
				found = True
				break
			# interior hole that touch the outline
			elif (coedge and l0[0] == l1[0] and l0[0] == edge[0]
					and dot(p1 - a0[0]-a0[1]*(p1[sortdim]-a0[0][sortdim]), y) > 0 
					and dot(p1 - a1[0]-a1[1]*(p1[sortdim]-a1[0][sortdim]), y) < 0):
				clusters[i] = (l0, coedge, a0, affine(coedge))
				clusters.insert(i, (edge, l1, affine(edge), a1))
				loops.insert(i, [edge[0]])
				print('      root hole', edge[0])
				found = True
				break
			# interior hole
			elif (coedge 
					and dot(p0 - a0[0]-a0[1]*(p0[sortdim]-a0[0][sortdim]), y) > 0 
					and dot(p0 - a1[0]-a1[1]*(p0[sortdim]-a1[0][sortdim]), y) < 0):
				clusters[i] = (l0, coedge, a0, affine(coedge))
				clusters.insert(i, (edge, l1, affine(edge), a1))
				loops[i].insert(0, coedge[0])
				loops.insert(i, [l1[0], edge[0]])
				print('      hole for ',i, edge)
				nprint(clusters)
				found = True
				break
			i += 1
		if not found:
		# if it's a new corner
			if coedge and edge[1] != coedge[1]:
				c = (coedge, edge, affine(coedge), affine(edge))
				# find the place to insert the cluster
				# NOTE a dichotomy is more efficient, but for now ...
				j = 0
				for j in range(len(clusters)):
					ci, cp = c[2], clusters[j][3]
					if (ci[0][sortdim], orthoproj(ci[1])) >= (cp[0][sortdim], orthoproj(cp[1])):
						break
				clusters.insert(j, c)
				loops.insert(j, [edge[0]])
				print('    new cluster', j)
				nprint(clusters)
			elif pts[edge[1]][sortdim] == pts[edge[0]][sortdim]:
				print('    restack')
				stack.insert(-1, edge)
				if coedge:	stack.insert(-1, coedge)
			else:
				pass
				raise Exception("algorithm failure, can be due to the given outline")
	
	# close clusters' ends
	for i,cluster in enumerate(clusters):
		l0,l1,a0,a1 = cluster
		loops[i].append(l0[1])
		if l0[1] != l1[1]:
			loops[i].insert(0, l1[1])
	finalized.extend(loops)
	#finalized = [l  for l in finalized if len(l) >= 3]
	#print('loops', finalized)
	
	return finalized

	
def sweepline_loops(lines: Web, normal=None):
	''' sweep line algorithm to retreive loops from a Web
		the web edges should not be oriented, and thus the resulting face has no orientation
		complexity: O(n*ln2(n))
	'''
	if len(lines.edges) < 3:	return Mesh()
	loops = []
	finalized = []
	x,y,z = guessbase(lines.points, normal)
	pts = {}
	for e in lines.edges:
		for i in e:
			if i not in pts:
				p = lines.points[i]
				pts[i] = vec2(dot(p,x), dot(p,y))
	
	def affine(e):
		v = pts[e[1]] - pts[e[0]]
		return (pts[e[0]], v/v[0] if v[0] else vec2(0))
	def projy(e, x):
		a, b = pts[e[0]], pts[e[1]]
		v = b-a
		return a[1] + (v[1]/v[0] if v[0] else 0) * (x - a[0])
	
	# direction of direct rotation of the outline, orthogonal to the sweepline direction
	print('sortdim', x, 'y', y)
	def orthoproj(v):
		l = sqrt(v[0]**2 + v[1]**2)
		return v[1] / l if l else 0
	
	# orient edges along the axis and sort them
	# sorting is done using absciss and orientation in case of similar absciss
	# the nearest directions to +-y is prefered to speedup cluster distinction
	edges = lines.edges[:]
	for i,(a,b) in enumerate(edges):
		if pts[a][0] < pts[b][0]:	edges[i] = b,a
	stack = sorted(edges,
				key=lambda e: (pts[e[0]][0], -abs(orthoproj(pts[e[1]]-pts[e[0]])) )
				)
	# remove absciss ambiguity (for edges that share points with the same absciss)
	# for each edge, all following edges with the same absciss and contains its start point will have the same startpoint
	for i in reversed(range(len(stack))):
		l = stack[i][0]
		n = i-1
		for j in reversed(range(i)):
			if pts[stack[j][0]][0] < pts[l][0]:	break
			if stack[j][1] == l:	
				stack[j] = (stack[j][1], stack[j][0])
			if stack[j][0] == l and n != j:
				stack.insert(n, stack.pop(j))
				n -= 1
	#print('stack', stack)
	print('stack')
	for e in stack:
		print(e, (pts[e[0]][0], orthoproj(pts[e[1]]-pts[e[0]])))
	
	# build cluster by cluster -  each cluster is a monotone sub-polygon
	clusters = []
	while stack:
		edge = stack.pop()
		# get the pair edge if there is one starting at the same point
		m = None
		sc = -1
		i = len(stack)-1
		while i >= 0 and pts[stack[i][0]][0] == pts[edge[0]][0]:
			e = stack[i]
			if e[0] == edge[0]:
				diff = abs(orthoproj(pts[e[1]]-pts[e[0]]) - orthoproj(pts[edge[1]]-pts[edge[0]]))
				if diff > sc:	
					sc = diff
					m = i
			i -= 1
		if m is not None:	
			coedge = stack.pop(m)
			if orthoproj(pts[edge[1]]-pts[edge[0]]) < orthoproj(pts[coedge[1]]-pts[coedge[0]]):
				edge, coedge = coedge, edge
		else:
			coedge = None
				
		print('stack', stack)
		print('*', edge, coedge, pts[edge[0]][0])
		
		# search in which cluster we are
		found = False
		i = 0
		while i < len(clusters):
			p0, p1 = pts[edge[0]], pts[edge[1]]
			l0,l1 = clusters[i]
			
			if l0[1] == l1[1]:
				print('    pop', l0,l1)
				clusters.pop(i)
				loops[i].append(l0[1])
				finalized.append(loops.pop(i))
				continue
			
			print('   ', l0,l1,edge[0])
			# continuation of already existing edge of the cluster
			if edge[0] == l0[1]:
				loops[i].append(l0[1])
				clusters[i] = (edge, l1)
				if coedge:
					stack.append(coedge)
				print('      continuation', edge)
				#if coedge:	nprint(clusters)
				found = True
				break
			elif edge[0] == l1[1]:
				loops[i].insert(0, l1[1])
				clusters[i] = (l0, coedge or edge)
				if coedge:
					stack.append(edge)
				print('      continuation', coedge or edge)
				#if coedge:	nprint(clusters)
				found = True
				break
			# interior hole that touch the outline
			elif (coedge and l0[0] == l1[0] and l0[0] == edge[0]
					and projy(l0, pts[e[1]][0]) > 0
					and projy(l1, pts[e[1]][0]) < 0):
				clusters[i] = (l0, coedge)
				clusters.insert(i, (edge, l1))
				loops.insert(i, [edge[0]])
				print('      root hole', edge[0])
				found = True
				break
			# interior hole
			elif (coedge 
					and projy(l0, pts[e[0]][0]) > 0
					and projy(l0, pts[e[1]][0]) < 0):
				clusters[i] = (l0, coedge)
				clusters.insert(i, (edge, l1))
				loops[i].insert(0, coedge[0])
				loops.insert(i, [l1[0], edge[0]])
				print('      hole for ',i, edge)
				nprint(clusters)
				found = True
				break
			i += 1
		if not found:
		# if it's a new corner
			if coedge and edge[1] != coedge[1]:
				c = (coedge, edge)
				# find the place to insert the cluster
				# NOTE a dichotomy is more efficient, but for now ...
				j = 0
				for j in range(len(clusters)):
					l0, l1 = clusters[j]
					if (pts[l0[0]][0], projy(l0, pts[edge[0]][0])) >= (pts[l1[0]][0], projy(l1, pts[edge[1]][0])):
						break
				clusters.insert(j, c)
				loops.insert(j, [edge[0]])
				print('    new cluster', j)
				nprint(clusters)
			elif pts[edge[1]][0] == pts[edge[0]][0]:
				print('    restack')
				stack.insert(-1, edge)
				if coedge:	stack.insert(-1, coedge)
			else:
				pass
				raise Exception("algorithm failure, can be due to the given outline")
	
	# close clusters' ends
	for i,cluster in enumerate(clusters):
		l0,l1 = cluster
		loops[i].append(l0[1])
		if l0[1] != l1[1]:
			loops[i].insert(0, l1[1])
	finalized.extend(loops)
	#finalized = [l  for l in finalized if len(l) >= 3]
	#print('loops', finalized)
	
	return finalized


def triangulation_sweepline(outline: Web) -> Mesh:
	''' extract loops from the web using sweepline_loops and trianglate them.
		the resulting mesh have one group per loop, and all the normals have approximately the same direction (they are coherent)
	'''
	m = Mesh(outline.points)
	for loop in sweepline_loops(outline):
		m += triangulation_outline(Wire(outline.points, loop))
	return m
