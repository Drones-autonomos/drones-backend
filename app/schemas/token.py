from pydantic import BaseModel, Field


class Token(BaseModel):
  access_token: str = Field(
      ...,
      description="Token de autenticación Bearer JWT",
      examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
  )
  token_type: str = Field(
      default="bearer",
      description="Tipo de esquema de token",
      examples=["bearer"],
  )


class TokenPayload(BaseModel):
  sub: str | None = Field(
      default=None,
      description="Identificador del sujeto (user id)",
      examples=["1"],
  )