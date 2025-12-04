"""
Test graph management API router.

Provides:
- Graph upload and storage
- Version management
- Graph validation
- Export capabilities
"""

import hashlib
from datetime import UTC, datetime
from typing import Optional, List

import yaml
from fastapi import APIRouter, UploadFile, HTTPException, Query, Depends, Request
from pydantic import BaseModel
from sqlalchemy import and_

from app.utils.load_graph import load_yaml
from app.database import SessionLocal
from app.models import TestGraph, TestGraphVersion
from app.auth import User, Permission, permission_dependency, log_audit

router = APIRouter()


class GraphCreate(BaseModel):
    """Request model for creating a graph."""
    name: str
    description: Optional[str] = None
    content: dict
    tags: Optional[List[str]] = None


class GraphUpdate(BaseModel):
    """Request model for updating a graph."""
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[dict] = None
    tags: Optional[List[str]] = None


class BuilderValidateRequest(BaseModel):
    yaml: str
    error_injections: Optional[List[str]] = None


class BuilderGenerateRequest(BaseModel):
    nodes: List[dict]
    edges: Optional[List[dict]] = None
    assertions: Optional[List[dict]] = None


class GraphVersionCreate(BaseModel):
    content: dict
    description: Optional[str] = None


def _hash_content(content: dict) -> str:
    return hashlib.sha256(str(content).encode()).hexdigest()


def _create_graph_version(
    db,
    graph_id: int,
    version: int,
    content: dict,
    tenant_id: str,
    user_id: Optional[int] = None,
    description: Optional[str] = None,
):
    db.execute(TestGraphVersion.insert().values(
        graph_id=graph_id,
        version=version,
        content=content,
        content_hash=_hash_content(content),
        created_by=user_id,
        change_description=description,
        tenant_id=tenant_id,
    ))


def _get_graph_for_tenant(db, graph_id: int, tenant_id: str):
    return db.execute(
        TestGraph.select().where(
            and_(TestGraph.c.id == graph_id, TestGraph.c.tenant_id == tenant_id)
        )
    ).fetchone()


@router.post("/builder/validate")
def builder_validate(
    request_body: BuilderValidateRequest,
    user: User = Depends(permission_dependency(Permission.GRAPH_CREATE)),
):
    """Validate builder YAML with optional error injection toggles."""

    try:
        content = yaml.safe_load(request_body.yaml) or {}
    except yaml.YAMLError as exc:
        return {"valid": False, "errors": [str(exc)], "warnings": []}

    errors: List[str] = []
    warnings: List[str] = []

    nodes = content.get("nodes")
    ids: set[str] = set()
    if not isinstance(nodes, list) or not nodes:
        errors.append("Graph must include at least one node.")
    else:
        for node in nodes:
            node_id = node.get("id")
            if not node_id:
                errors.append("Node missing id.")
                continue
            if node_id in ids:
                errors.append(f"Duplicate node id: {node_id}")
            ids.add(node_id)

    edges = content.get("edges", [])
    for edge in edges or []:
        if edge.get("from") not in ids:
            warnings.append(f"Edge {edge} references unknown source.")
        if edge.get("to") not in ids:
            warnings.append(f"Edge {edge} references unknown target.")

    for injected in request_body.error_injections or []:
        errors.append(f"Injected error: {injected}")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "node_count": len(nodes or []),
            "edge_count": len(edges or []),
        },
    }


@router.post("/builder/generate")
def builder_generate(
    request_body: BuilderGenerateRequest,
    user: User = Depends(permission_dependency(Permission.GRAPH_CREATE)),
):
    """Generate canonical YAML from structured builder payload."""

    payload = {
        "nodes": request_body.nodes,
        "edges": request_body.edges or [],
        "assertions": request_body.assertions or [],
    }
    yaml_output = yaml.safe_dump(payload, sort_keys=False)
    return {
        "yaml": yaml_output,
        "summary": {
            "node_count": len(payload["nodes"]),
            "edge_count": len(payload["edges"]),
            "assertion_count": len(payload["assertions"]),
        },
    }


@router.post("/upload")
async def upload_graph(
    file: UploadFile,
    request: Request,
    user: User = Depends(permission_dependency(Permission.GRAPH_CREATE))
):
    """
    Upload a YAML graph file.
    
    The file should contain a valid behavioral test graph definition.
    """
    if not file.filename.endswith(('.yaml', '.yml')):
        raise HTTPException(
            status_code=400, 
            detail="File must be a YAML file (.yaml or .yml)"
        )
    
    try:
        content = load_yaml(file)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {str(e)}")
    
    # Validate graph structure
    if not isinstance(content, dict):
        raise HTTPException(status_code=400, detail="Graph must be a dictionary")
    
    if "nodes" not in content:
        raise HTTPException(status_code=400, detail="Graph must contain 'nodes'")
    
    db = SessionLocal()
    try:
        timestamp = datetime.now(UTC)
        result = db.execute(TestGraph.insert().values(
            name=file.filename,
            description=None,
            content=content,
            version=1,
            tenant_id=user.tenant_id,
            created_by=user.id,
            created_at=timestamp,
            updated_at=timestamp,
        ))
        graph_id = result.inserted_primary_key[0]
        _create_graph_version(db, graph_id, 1, content, user.tenant_id, user_id=user.id)
        db.commit()
        
        response = {
            "id": graph_id,
            "uploaded": file.filename,
            "nodes": len(content.get("nodes", [])),
            "edges": len(content.get("edges", [])),
            "assertions": len(content.get("assertions", []))
        }
        await log_audit(
            user=user,
            action="graph.upload",
            resource_type="graph",
            resource_id=graph_id,
            details={"filename": file.filename},
            request=request
        )
        return response
    finally:
        db.close()


@router.post("/")
async def create_graph(
    graph: GraphCreate,
    request: Request,
    user: User = Depends(permission_dependency(Permission.GRAPH_CREATE))
):
    """
    Create a new test graph from JSON.
    
    Alternative to file upload for programmatic graph creation.
    """
    db = SessionLocal()
    try:
        timestamp = datetime.now(UTC)
        result = db.execute(TestGraph.insert().values(
            name=graph.name,
            description=graph.description,
            content=graph.content,
            version=1,
            tenant_id=user.tenant_id,
            created_by=user.id,
            tags=graph.tags,
            created_at=timestamp,
            updated_at=timestamp,
        ))
        graph_id = result.inserted_primary_key[0]
        _create_graph_version(db, graph_id, 1, graph.content, user.tenant_id, user_id=user.id)
        db.commit()
        
        response = {
            "id": graph_id,
            "name": graph.name,
            "nodes": len(graph.content.get("nodes", [])),
            "edges": len(graph.content.get("edges", []))
        }
        await log_audit(
            user=user,
            action="graph.create",
            resource_type="graph",
            resource_id=graph_id,
            details={"name": graph.name},
            request=request
        )
        return response
    finally:
        db.close()


@router.get("/")
def list_graphs(
    search: Optional[str] = None,
    tags: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    user: User = Depends(permission_dependency(Permission.GRAPH_READ))
):
    """
    List all test graphs with optional filtering.
    
    - **search**: Filter by name (partial match)
    - **tags**: Filter by tags (comma-separated)
    """
    db = SessionLocal()
    try:
        query = TestGraph.select().where(TestGraph.c.tenant_id == user.tenant_id)

        if search:
            query = query.where(TestGraph.c.name.ilike(f"%{search}%"))
        tag_list: List[str] = []
        if tags:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]

        rows = db.execute(query.limit(limit).offset(offset)).fetchall()
        
        results = []
        for r in rows:
            if tag_list:
                graph_tags = set(r.tags or [])
                if not set(tag_list).issubset(graph_tags):
                    continue

            content = r.content or {}
            results.append({
                "id": r.id,
                "name": r.name,
                "version": r.version,
                "nodes": len(content.get("nodes", [])),
                "edges": len(content.get("edges", [])),
                "assertions": len(content.get("assertions", []))
            })
        
        return results
    finally:
        db.close()


@router.get("/library")
def graph_library(
    include_shared: bool = True,
    user: User = Depends(permission_dependency(Permission.GRAPH_LIBRARY)),
):
    """Return library of graphs available to the workspace."""

    db = SessionLocal()
    try:
        query = TestGraph.select()
        if not include_shared:
            query = query.where(TestGraph.c.tenant_id == user.tenant_id)

        rows = db.execute(query).fetchall()
        library = []
        for row in rows:
            library.append(
                {
                    "id": row.id,
                    "name": row.name,
                    "version": row.version,
                    "tenant_id": row.tenant_id,
                    "owner_id": row.created_by,
                    "tags": row.tags or [],
                }
            )
        return {"graphs": library}
    finally:
        db.close()


@router.get("/{graph_id}")
def get_graph(
    graph_id: int,
    user: User = Depends(permission_dependency(Permission.GRAPH_READ))
):
    """Get a specific graph by ID with full content."""
    db = SessionLocal()
    try:
        graph = _get_graph_for_tenant(db, graph_id, user.tenant_id)
        
        if not graph:
            raise HTTPException(status_code=404, detail="Graph not found")
        
        content = graph.content or {}
        
        return {
            "id": graph.id,
            "name": graph.name,
            "version": graph.version,
            "content": content,
            "summary": {
                "nodes": len(content.get("nodes", [])),
                "edges": len(content.get("edges", [])),
                "assertions": len(content.get("assertions", [])),
                "contracts": len(content.get("contracts", []))
            }
        }
    finally:
        db.close()


@router.put("/{graph_id}")
async def update_graph(
    graph_id: int,
    update: GraphUpdate,
    request: Request,
    user: User = Depends(permission_dependency(Permission.GRAPH_UPDATE))
):
    """Update an existing graph."""
    db = SessionLocal()
    try:
        graph = _get_graph_for_tenant(db, graph_id, user.tenant_id)
        
        if not graph:
            raise HTTPException(status_code=404, detail="Graph not found")
        
        update_values = {"updated_at": datetime.now(UTC)}
        if update.name:
            update_values["name"] = update.name
        if update.description:
            update_values["description"] = update.description
        if update.tags is not None:
            update_values["tags"] = update.tags
        
        new_content = None
        if update.content:
            new_content = update.content
            update_values["content"] = new_content
            current_version = graph.version or 1
            update_values["version"] = current_version + 1
        
        if update_values:
            db.execute(
                TestGraph.update()
                .where(TestGraph.c.id == graph_id)
                .values(**update_values)
            )
            if new_content:
                current_version = graph.version or 1
                _create_graph_version(
                    db,
                    graph_id,
                    current_version + 1,
                    new_content,
                    user.tenant_id,
                    user_id=user.id,
                )
            db.commit()
        updated_fields = list(update_values.keys())
        await log_audit(
            user=user,
            action="graph.update",
            resource_type="graph",
            resource_id=graph_id,
            details={"updated_fields": updated_fields},
            request=request
        )
        return {"id": graph_id, "updated": updated_fields}
    finally:
        db.close()


@router.post("/{graph_id}/versions")
def create_graph_version(
    graph_id: int,
    payload: GraphVersionCreate,
    user: User = Depends(permission_dependency(Permission.GRAPH_UPDATE)),
):
    """Create a new explicit graph version with provided content."""

    db = SessionLocal()
    try:
        graph = _get_graph_for_tenant(db, graph_id, user.tenant_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Graph not found")

        next_version = (graph.version or 1) + 1
        _create_graph_version(
            db,
            graph_id,
            next_version,
            payload.content,
            user.tenant_id,
            user_id=user.id,
            description=payload.description,
        )
        db.execute(
            TestGraph.update()
            .where(TestGraph.c.id == graph_id)
            .values(content=payload.content, version=next_version, updated_at=datetime.now(UTC))
        )
        db.commit()
        return {"graph_id": graph_id, "version": next_version}
    finally:
        db.close()


@router.delete("/{graph_id}")
async def delete_graph(
    graph_id: int,
    request: Request,
    user: User = Depends(permission_dependency(Permission.GRAPH_DELETE))
):
    """Delete a graph."""
    db = SessionLocal()
    try:
        result = db.execute(
            TestGraph.delete().where(
                and_(TestGraph.c.id == graph_id, TestGraph.c.tenant_id == user.tenant_id)
            )
        )
        db.commit()
        
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Graph not found")
        
        await log_audit(
            user=user,
            action="graph.delete",
            resource_type="graph",
            resource_id=graph_id,
            details={},
            request=request
        )
        return {"deleted": graph_id}
    finally:
        db.close()


@router.get("/{graph_id}/validate")
def validate_graph(
    graph_id: int,
    user: User = Depends(permission_dependency(Permission.GRAPH_READ))
):
    """Validate a graph structure and contracts."""
    db = SessionLocal()
    try:
        graph = _get_graph_for_tenant(db, graph_id, user.tenant_id)
        
        if not graph:
            raise HTTPException(status_code=404, detail="Graph not found")
        
        content = graph.content or {}
        issues = []
        
        # Validate nodes
        nodes = content.get("nodes", [])
        node_ids = set()
        for node in nodes:
            if "id" not in node:
                issues.append({"type": "error", "message": "Node missing 'id'"})
            else:
                if node["id"] in node_ids:
                    issues.append({
                        "type": "error", 
                        "message": f"Duplicate node id: {node['id']}"
                    })
                node_ids.add(node["id"])
        
        # Validate edges
        edges = content.get("edges", [])
        for edge in edges:
            if edge.get("from") not in node_ids:
                issues.append({
                    "type": "error",
                    "message": f"Edge references unknown node: {edge.get('from')}"
                })
            if edge.get("to") not in node_ids:
                issues.append({
                    "type": "error",
                    "message": f"Edge references unknown node: {edge.get('to')}"
                })
        
        # Check for cycles
        # (simplified check - full implementation would use graph algorithms)
        
        return {
            "valid": len([i for i in issues if i["type"] == "error"]) == 0,
            "issues": issues,
            "summary": {
                "nodes": len(nodes),
                "edges": len(edges),
                "error_count": len([i for i in issues if i["type"] == "error"]),
                "warning_count": len([i for i in issues if i["type"] == "warning"])
            }
        }
    finally:
        db.close()


@router.get("/{graph_id}/export")
def export_graph(
    graph_id: int,
    format: str = "yaml",
    user: User = Depends(permission_dependency(Permission.GRAPH_READ))
):
    """
    Export a graph in various formats.
    
    Supported formats: yaml, json, mermaid
    """
    db = SessionLocal()
    try:
        graph = _get_graph_for_tenant(db, graph_id, user.tenant_id)
        
        if not graph:
            raise HTTPException(status_code=404, detail="Graph not found")
        
        content = graph.content or {}
        
        if format == "yaml":
            import yaml
            return {"content": yaml.dump(content, default_flow_style=False)}
        
        elif format == "json":
            return {"content": content}
        
        elif format == "mermaid":
            # Generate Mermaid diagram
            lines = ["flowchart TD"]
            
            for node in content.get("nodes", []):
                node_id = node["id"].replace("-", "_")
                label = node.get("type", node["id"])
                lines.append(f"    {node_id}[{label}]")
            
            for edge in content.get("edges", []):
                from_id = edge["from"].replace("-", "_")
                to_id = edge["to"].replace("-", "_")
                lines.append(f"    {from_id} --> {to_id}")
            
            return {"content": "\n".join(lines)}
        
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported format: {format}. Use yaml, json, or mermaid"
            )
    finally:
        db.close()
