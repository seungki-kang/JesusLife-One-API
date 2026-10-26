from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from app.core.auth import AuthContext, get_current_user
from .schemas import CompletionRecordMetadata, CompletionUpdate, CompletionDelete, CompletionResult
from .store import CompletionStore, get_completion_store
from .service import CompletionService


router = APIRouter(prefix="/api/v1/neorang-narang", tags=["neorang-narang"])


@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "neorang-narang",
        "version": "0.1.0",
    }




class SafeValidationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(status_code=422, detail='Invalid request') from None
        return handler


completions = APIRouter(prefix='/completions', route_class=SafeValidationRoute)


def service(user: AuthContext = Depends(get_current_user),
            store: CompletionStore = Depends(get_completion_store)) -> CompletionService:
    return CompletionService(store, user)


@completions.post('', response_model=CompletionResult, status_code=201,
                  responses={200: {'model': CompletionResult, 'description': 'Identical create replay'},
                             401: {'description': 'Authentication required'},
                             409: {'description': 'Record or revision conflict'}})
def create_completion(metadata: CompletionRecordMetadata, response: Response,
                      svc: CompletionService = Depends(service)):
    result, created = svc.create(metadata)
    response.status_code = 201 if created else 200
    return result


@completions.get('', response_model=list[CompletionRecordMetadata])
def list_completions(limit: int = Query(default=10, ge=1, le=20),
                     svc: CompletionService = Depends(service)):
    return svc.list(limit)


@completions.get('/{record_id}', response_model=CompletionRecordMetadata,
                 responses={401: {'description': 'Authentication required'},
                            404: {'description': 'Not Found'}})
def get_completion(record_id: UUID, svc: CompletionService = Depends(service)):
    return svc.get(record_id)


@completions.put('/{record_id}', response_model=CompletionResult,
                 responses={401: {'description': 'Authentication required'},
                            404: {'description': 'Not Found'},
                            409: {'description': 'Revision conflict'}})
def update_completion(record_id: UUID, command: CompletionUpdate,
                      svc: CompletionService = Depends(service)):
    return svc.update(record_id, command.base_revision, command.metadata)


@completions.delete('/{record_id}', response_model=CompletionResult,
                    responses={401: {'description': 'Authentication required'},
                               404: {'description': 'Not Found'},
                               409: {'description': 'Revision conflict'}})
def delete_completion(record_id: UUID, command: CompletionDelete,
                      svc: CompletionService = Depends(service)):
    return svc.delete(record_id, command.base_revision, command.revision)


router.include_router(completions)
