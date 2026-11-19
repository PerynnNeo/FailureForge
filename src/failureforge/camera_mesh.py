"""Read supplied STL bytes as triangles and prepare indexed camera surfaces."""
import numpy as np


def stl_triangles(blob):
    """Return facet positions in file units. A binary header may also start with 'solid'."""
    count = int.from_bytes(blob[80:84], "little")
    if len(blob) >= 84 and 84 + count * 50 == len(blob):
        if not 1 <= count <= 100_000:
            raise ValueError("Unsupported STL facet count")
        facet_type = np.dtype([("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")])
        points = np.frombuffer(blob, facet_type, count=count, offset=84)["vertices"].astype(float)
    else:
        lines = iter(line.split() for line in blob.decode("ascii").splitlines() if line.strip())
        if next(lines, [])[:1] != ["solid"]:
            raise ValueError("Expected binary or ASCII STL")
        facets = []
        for line in lines:
            if line[:1] == ["endsolid"]:
                if next(lines, None) is not None:
                    raise ValueError("Expected one STL solid")
                break
            if line[:2] != ["facet", "normal"] or len(line) != 5 or next(lines, []) != ["outer", "loop"]:
                raise ValueError("Invalid ASCII STL facet")
            triangle = []
            for _ in range(3):
                vertex = next(lines, [])
                if vertex[:1] != ["vertex"] or len(vertex) != 4:
                    raise ValueError("Invalid ASCII STL vertex")
                triangle.append([float(value) for value in vertex[1:]])
            if next(lines, []) != ["endloop"] or next(lines, []) != ["endfacet"]:
                raise ValueError("Incomplete ASCII STL facet")
            facets.append(triangle)
            if len(facets) > 100_000:
                raise ValueError("Unsupported STL facet count")
        else:
            raise ValueError("Missing STL endsolid")
        points = np.asarray(facets, dtype=float)
    if not points.size or not np.isfinite(points).all():
        raise ValueError("STL needs finite vertices")
    return points


def mesh_surface(triangles, max_faces=2000):
    """Bound render cost by clustering nearby vertices, keeping adjoining facets connected."""
    points = np.asarray(triangles, dtype=float)
    if points.ndim != 3 or points.shape[1:] != (3, 3) or not len(points) or not np.isfinite(points).all():
        raise ValueError("Expected finite triangles")
    flat = points.reshape(-1, 3)
    vertices, ids = np.unique(flat, axis=0, return_inverse=True)
    faces = ids.reshape(-1, 3)
    if len(faces) <= max_faces:
        return vertices, faces, False
    low = vertices.min(axis=0)
    extent = float(np.ptp(vertices, axis=0).max())
    if extent <= 0:
        raise ValueError("STL has no extent")
    for resolution in (80, 48, 32, 24, 18, 14, 10, 7, 4, 2):
        cells = np.floor((vertices - low) * (resolution / extent)).astype(np.int32)
        _, cluster = np.unique(cells, axis=0, return_inverse=True)
        cluster = cluster.ravel()
        reduced = cluster[faces]
        reduced = reduced[(reduced[:, 0] != reduced[:, 1]) & (reduced[:, 0] != reduced[:, 2]) &
                          (reduced[:, 1] != reduced[:, 2])]
        _, unique = np.unique(np.sort(reduced, axis=1), axis=0, return_index=True)
        if 0 < len(unique) <= max_faces:
            counts = np.bincount(cluster)
            centers = np.column_stack([np.bincount(cluster, weights=vertices[:, axis]) / counts for axis in range(3)])
            return centers, reduced[np.sort(unique)], True
    raise ValueError("STL surface could not be reduced")
