# kate: syntax perl

requires 'String::Util';
requires 'IPC::System::Simple';
requires 'File::Which';

on 'build' => sub {
  requires 'App::FatPacker';
};
